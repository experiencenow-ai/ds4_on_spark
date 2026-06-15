#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent import futures
import json
import re
import time
from pathlib import Path
from urllib import parse, request
import uuid

SYSTEM_PROMPT = (
    "You are solving a hard benchmark question. Reason carefully. "
    "The final answer must follow the requested format exactly."
)
REQUEST_FORMAT = "ds4-inference-request-v1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_C = ROOT / "fixtures" / "ds4_eval" / "ds4_eval.c"
TERMINAL = {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}
RESPONSE_STYLES = ("official", "concise", "answer_only", "answer_first", "compsec_strict")


def _post_json(base_url: str, endpoint: str, payload: dict, *, timeout: float = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        base_url.rstrip("/") + endpoint,
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(base_url: str, endpoint: str, query: dict[str, object] | None = None) -> dict:
    suffix = ""
    if query:
        suffix = "?" + parse.urlencode({k: v for k, v in query.items() if v is not None})
    with request.urlopen(base_url.rstrip("/") + endpoint + suffix, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_text(base_url: str, endpoint: str, *, timeout: float = 120.0) -> str:
    with request.urlopen(base_url.rstrip("/") + endpoint, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _find_matching_brace(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unclosed brace")


def _split_case_entries(body: str) -> list[str]:
    entries: list[str] = []
    i = 0
    while i < len(body):
        if body[i] != "{":
            i += 1
            continue
        end = _find_matching_brace(body, i)
        entries.append(body[i + 1 : end])
        i = end + 1
    return entries


def _decode_c_strings(value: str) -> str:
    out: list[str] = []
    for match in re.finditer(r'"((?:\\.|[^"\\])*)"', value, flags=re.S):
        raw = match.group(1)
        decoded = bytes(raw, "utf-8").decode("unicode_escape")
        out.append(decoded)
    return "".join(out)


def _field_values(entry: str) -> dict[str, str | list[str]]:
    fields: dict[str, str | list[str]] = {"choice": []}
    pos = 0
    pattern = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?\s*=\s*", re.S)
    while True:
        match = pattern.search(entry, pos)
        if match is None:
            break
        value_start = match.end()
        value_end = value_start
        in_string = False
        escape = False
        while value_end < len(entry):
            ch = entry[value_end]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == ",":
                break
            value_end += 1
        value = _decode_c_strings(entry[value_start:value_end])
        name = match.group(1)
        index = match.group(2)
        if name == "choice" and index is not None:
            choices = fields["choice"]
            assert isinstance(choices, list)
            idx = int(index)
            while len(choices) <= idx:
                choices.append("")
            choices[idx] = value
        else:
            fields[name] = value
        pos = value_end + 1
    choices = fields["choice"]
    assert isinstance(choices, list)
    while choices and not choices[-1]:
        choices.pop()
    return fields


def parse_eval_cases(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    marker = "static const eval_case eval_cases[] ="
    start = text.index(marker)
    open_brace = text.index("{", start)
    close_brace = _find_matching_brace(text, open_brace)
    cases: list[dict] = []
    for idx, entry in enumerate(_split_case_entries(text[open_brace + 1 : close_brace])):
        fields = _field_values(entry)
        if "source" not in fields or "id" not in fields or "question" not in fields or "answer" not in fields:
            continue
        choices = fields.get("choice", [])
        if not isinstance(choices, list):
            choices = []
        cases.append(
            {
                "index": idx,
                "source": str(fields.get("source", "")),
                "id": str(fields.get("id", "")),
                "domain": str(fields.get("domain", "")),
                "title": str(fields.get("title", "")),
                "question": str(fields.get("question", "")),
                "choices": [str(item) for item in choices if item],
                "answer": str(fields.get("answer", "")),
            }
        )
    return cases


def _source_filters(args: argparse.Namespace) -> list[str]:
    return [str(item) for item in getattr(args, "source", []) or [] if str(item)]


def _filter_cases(cases: list[dict], sources: list[str]) -> list[dict]:
    if not sources:
        return cases
    wanted = set(sources)
    filtered = [case for case in cases if case.get("source") in wanted]
    if not filtered:
        raise ValueError(f"no ds4-eval cases matched --source {','.join(sources)}")
    return filtered


def _request_payload_source(row: dict) -> str:
    meta = ((row.get("input") or {}).get("metadata") or {}).get("ds4_eval") or {}
    return str(meta.get("source") or "") if isinstance(meta, dict) else ""


def _filter_request_payloads(rows: list[dict], sources: list[str]) -> list[dict]:
    if not sources:
        return rows
    wanted = set(sources)
    filtered = [row for row in rows if _request_payload_source(row) in wanted]
    if not filtered:
        raise ValueError(f"no ds4-eval requests matched --source {','.join(sources)}")
    return filtered


def build_question_prompt(case: dict, *, response_style: str = "official") -> str:
    parts = [case["question"] + "\n"]
    choices = case.get("choices") or []
    if choices:
        parts.append("\nChoices:\n")
        for idx, choice in enumerate(choices):
            parts.append(f"{chr(ord('A') + idx)}. {choice}\n")
        parts.append(_answer_instruction(response_style, "letter"))
    elif case.get("source") == "COMPSEC":
        parts.append(_answer_instruction(response_style, "line number or comma-separated line numbers"))
    else:
        parts.append(_answer_instruction(response_style, "integer"))
    return "".join(parts)


def _answer_instruction(response_style: str, answer_type: str) -> str:
    if response_style == "official":
        if answer_type == "letter":
            return (
                "\nSolve the question. At the end, write exactly one final line in this "
                "format and do not write anything after it:\n"
                "Answer: <letter>"
            )
        return (
            "\nSolve the problem. At the end, write exactly one final line in this "
            "format and do not write anything after it:\n"
            f"Answer: <{answer_type}>"
        )
    if response_style == "answer_first":
        return (
            "\nSolve the problem silently. Put the final answer on the first line in "
            "exactly this format:\n"
            f"Answer: <{answer_type}>\n"
            "After that line you may add a brief explanation."
        )
    if response_style == "concise":
        return (
            "\nSolve the problem. Keep visible reasoning to at most three short "
            "sentences. End with exactly one final line and nothing after it:\n"
            f"Answer: <{answer_type}>"
        )
    if response_style == "answer_only":
        return (
            "\nSolve the problem silently. Output exactly one line and nothing else:\n"
            f"Answer: <{answer_type}>"
        )
    if response_style == "compsec_strict":
        if "line number" in answer_type:
            return (
                "\nSolve the problem carefully. For line-number answers, prefer the "
                "exact executable line or smallest adjacent set of lines where the "
                "unsafe access, unchecked copy/write/read, invalid state transition, "
                "or missing validation becomes concrete. Do not include earlier setup "
                "or loop-control lines unless those lines themselves perform the "
                "invalid operation. If a later use is required to make the bug real, "
                "include that use. Keep visible reasoning to at most three short "
                "sentences. End with exactly one final line and nothing after it:\n"
                f"Answer: <{answer_type}>"
            )
        return (
            "\nSolve the problem carefully. Keep visible reasoning to at most three "
            "short sentences. End with exactly one final line and nothing after it:\n"
            f"Answer: <{answer_type}>"
        )
    raise ValueError(f"unsupported response style: {response_style}")


def render_prompt(vllm_url: str, model: str, question_prompt: str, max_tokens: int, *, enable_thinking: bool, thinking_key: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    if thinking_key:
        payload["chat_template_kwargs"] = {thinking_key: bool(enable_thinking)}
    rendered = _post_json(vllm_url, "/v1/chat/completions/render", payload)
    token_ids = rendered.get("token_ids")
    if not isinstance(token_ids, list):
        raise ValueError(f"render endpoint did not return token_ids: {rendered}")
    detok = _post_json(vllm_url, "/detokenize", {"model": model, "tokens": token_ids})
    prompt = detok.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError(f"detokenize endpoint did not return prompt: {detok}")
    if not enable_thinking and prompt.endswith("<think>"):
        prompt += "</think>"
    return prompt


def _skip_prompt_render(vllm_url: str) -> bool:
    return str(vllm_url or "").strip().lower() in {"", "none", "off", "skip", "dsapi"}


def write_requests(args: argparse.Namespace) -> None:
    cases = parse_eval_cases(Path(args.source_c))
    cases = _filter_cases(cases, _source_filters(args))
    if args.limit:
        cases = cases[: int(args.limit)]
    out = Path(args.out_jsonl)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for idx, case in enumerate(cases):
            payload = _eval_request_payload(args, idx, case)
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    _write_request_manifest(args, out, len(cases))


def _eval_request_payload(args: argparse.Namespace, idx: int, case: dict) -> dict:
    question_prompt = build_question_prompt(case, response_style=str(args.response_style))
    rendered = None
    if not _skip_prompt_render(args.vllm_url):
        rendered = render_prompt(
            args.vllm_url,
            args.served_model,
            question_prompt,
            args.max_output_tokens,
            enable_thinking=bool(args.enable_thinking),
            thinking_key=str(args.chat_template_thinking_key),
        )
    return {
        "format": REQUEST_FORMAT,
        "request_id": f"ds4-eval-{idx:03d}-{case['id']}",
        "capability": None,
        "chat": True,
        "immediate": False,
        "job_class": "analysis",
        "max_output_tokens": int(args.max_output_tokens),
        "thinking_budget_tokens": _effective_thinking_budget_tokens(args),
        "temperature": float(args.temperature),
        "input": _request_input_payload(case, question_prompt, rendered, idx),
        "output_contract": {"format": "text"},
        "model_pin": {"profile_id": args.model},
    }


def _effective_thinking_budget_tokens(args: argparse.Namespace) -> int:
    return int(args.thinking_budget_tokens) if bool(args.enable_thinking) else 0


def _request_input_payload(case: dict, question_prompt: str, rendered: str | None, idx: int) -> dict:
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question_prompt},
        ],
        "metadata": {
            "ds4_eval": _eval_metadata(case, idx),
        },
        "estimated_prompt_tokens": len((rendered or question_prompt).split()),
    }
    if rendered is not None:
        payload["rendered_prompt"] = rendered
        payload["prompt"] = question_prompt
        payload["metadata"]["rendered_prompt"] = rendered
    return payload


def _eval_metadata(case: dict, idx: int) -> dict:
    return {
        "index": idx,
        "source": case["source"],
        "id": case["id"],
        "domain": case["domain"],
        "title": case["title"],
        "answer": case["answer"],
        "choices": case["choices"],
    }


def _write_request_manifest(args: argparse.Namespace, out: Path, request_count: int) -> None:
    manifest = {
        "format": "ds4-eval-api-request-manifest-v1",
        "source_c": str(Path(args.source_c)),
        "source": _source_filters(args),
        "requests_jsonl": str(out),
        "request_count": request_count,
        "max_output_tokens": int(args.max_output_tokens),
        "enable_thinking": bool(args.enable_thinking),
        "thinking_budget_tokens": _effective_thinking_budget_tokens(args),
        "temperature": float(args.temperature),
        "response_style": str(args.response_style),
        "written_at": time.time(),
    }
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))


def _answer_region(text: str) -> str:
    pos = text.find("</think>")
    return text[pos + len("</think>") :] if pos >= 0 else text


def _last_answer_marker(text: str) -> int:
    last = _last_answer_colon_marker(text)
    if last >= 0:
        return last
    match = re.search(r"(?i)\banswer\b", text)
    return match.start() if match else -1


def _last_answer_colon_marker(text: str) -> int:
    last = -1
    for match in re.finditer(r"(?i)\banswer\b\s*:", text):
        last = match.start()
    return last


def _marker_value_span(text: str, start: int, limit: int) -> str:
    colon = text.find(":", start)
    if colon < 0:
        return ""
    span = text[colon + 1 : colon + 1 + limit]
    return span.splitlines()[0] if span else ""


def _letter_matches(text: str, nchoices: int) -> list[str]:
    max_letter = chr(ord("A") + nchoices - 1)
    letters: list[str] = []
    for match in re.finditer(r"\b[A-Z]\b", text.upper()):
        letter = match.group(0)
        if "A" <= letter <= max_letter:
            letters.append(letter)
    return letters


def _phrase_letter_answer(text: str, nchoices: int) -> str:
    max_letter = chr(ord("A") + nchoices - 1)
    patterns = [
        r"(?i)\b(?:final\s+)?answer\s+(?:is|=)\s*(?:option\s+|choice\s+)?([A-Z])\b",
        r"(?i)\b(?:correct|best|right)\s+(?:answer|option|choice)\s*(?:is|:)?\s*(?:option\s+|choice\s+)?([A-Z])\b",
        r"(?i)\b(?:select|choose|pick)\s+(?:the\s+)?(?:correct\s+)?(?:option|choice)\s*(?:is|:)?\s*(?:option\s+|choice\s+)?([A-Z])\b",
        r"(?i)\b(?:option|choice)\s+([A-Z])\s+(?:is|seems|appears)\s+(?:the\s+)?(?:correct|best|right|plausible)\b",
        r"(?i)\b(?:option|choice)\s+([A-Z])\s*[-:]\s*.*?\b(?:correct|best|right|plausible)\b",
        r"(?i)\b([A-Z])\.\s+.*?\b(?:correct|best|right|plausible)\b",
        r"(?i)\b(?:option|choice)\s+([A-Z])\s+corresponds\b",
    ]
    matches: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            letter = match.group(1).upper()
            if "A" <= letter <= max_letter:
                matches.append(letter)
    return matches[-1] if matches else "?"


def _letter_answer(text: str, nchoices: int) -> str:
    visible = _answer_region(text)
    start = _last_answer_colon_marker(visible)
    if start >= 0:
        letters = _letter_matches(_marker_value_span(visible, start, 96), nchoices)
        if letters:
            return letters[0]
    got = _phrase_letter_answer(visible, nchoices)
    if got != "?":
        return got
    letters = _letter_matches(visible, nchoices)
    return letters[-1] if letters else "?"


def _normalize_integer(raw: str) -> str:
    try:
        return str(int(raw))
    except ValueError:
        return raw.lstrip("0") or "0"


def _first_integer(text: str) -> str:
    match = re.search(r"\d+", text)
    return _normalize_integer(match.group(0)) if match else "?"


def _last_integer(text: str) -> str:
    matches = re.findall(r"\d+", text)
    return _normalize_integer(matches[-1]) if matches else "?"


def _phrase_integer_answer(text: str) -> str:
    patterns = [
        r"(?i)\b(?:final\s+)?answer\s+(?:is|=)\s*([0-9]+)\b",
        r"(?i)\b(?:result|value|sum|number)\s+(?:is|=)\s*([0-9]+)\b",
    ]
    matches: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            matches.append(_normalize_integer(match.group(1)))
    return matches[-1] if matches else "?"


def _integer_answer(text: str) -> str:
    visible = _answer_region(text)
    start = _last_answer_colon_marker(visible)
    if start >= 0:
        got = _first_integer(_marker_value_span(visible, start, 160))
        if got != "?":
            return got
    got = _phrase_integer_answer(visible)
    if got != "?":
        return got
    return _last_integer(visible)


def _line_spec(text: str) -> str:
    visible = _answer_region(text)
    start = _last_answer_colon_marker(visible)
    if start < 0:
        return _integer_answer(text)
    span = _marker_value_span(visible, start, 160)
    pieces = re.findall(r"\d+(?:\s*-\s*\d+)?", span)
    return ",".join(piece.replace(" ", "") for piece in pieces) if pieces else _integer_answer(text)


def _parse_line_spec(spec: str) -> set[int]:
    out: set[int] = set()
    for item in re.findall(r"\d+(?:-\d+)?", spec):
        if "-" in item:
            a, b = [int(part) for part in item.split("-", 1)]
            if a > b:
                a, b = b, a
            out.update(range(a, b + 1))
        else:
            out.add(int(item))
    return out


def _grade_one(meta: dict, text: str) -> tuple[str, bool]:
    choices = meta.get("choices") if isinstance(meta.get("choices"), list) else []
    expected = str(meta.get("answer", ""))
    if choices:
        got = _letter_answer(text, len(choices))
        return got, got == expected[:1]
    if meta.get("source") == "COMPSEC":
        got = _line_spec(text)
        got_set = _parse_line_spec(got)
        exp_set = _parse_line_spec(expected)
        return got, bool(got_set) and bool(exp_set) and got_set.issubset(exp_set)
    got = _integer_answer(text)
    try:
        expected_norm = str(int(expected))
    except ValueError:
        expected_norm = expected
    return got, got == expected_norm


def grade(args: argparse.Namespace) -> None:
    requests_by_id = _request_meta_by_id(_load_requests_jsonl(Path(args.requests_jsonl)))
    collect = json.loads(Path(args.collect_json).read_text(encoding="utf-8"))
    summary = grade_collect(requests_by_id, collect)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, sort_keys=True))


def grade_collect(requests_by_id: dict[str, dict], collect: dict) -> dict:
    rows = []
    passed = 0
    total = 0
    completion_tokens = 0
    for item in collect.get("results", []):
        request_id = str(item.get("request", {}).get("request_id") or item.get("result", {}).get("request_id"))
        meta = requests_by_id.get(request_id, {})
        result = item.get("result") or {}
        text = str((result.get("output") or {}).get("text") or "")
        got, ok = _grade_one(meta, text)
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        total += 1
        passed += 1 if ok else 0
        rows.append(
            {
                "index": meta.get("index"),
                "source": meta.get("source"),
                "id": meta.get("id"),
                "expected": meta.get("answer"),
                "got": got,
                "passed": ok,
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "text_preview": text[:240],
            }
        )
    summary = {
        "format": "ds4-eval-api-grade-v1",
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": round(passed / total, 6) if total else 0.0,
        "completion_tokens": completion_tokens,
        "rows": rows,
    }
    return summary


def run_direct_vllm_eval(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_id = args.batch_id or f"ds4-eval-direct-{uuid.uuid4().hex[:16]}"
    source_requests, requests_path, requests_payload = _prepare_run_requests(args, out_dir, batch_id)
    requests_by_id = _request_meta_by_id(requests_payload)
    cache_before = _cache_metrics_snapshot(args)
    collect, response, run_s = _run_direct_vllm_batch(args, requests_payload)
    cache_metrics = _cache_metrics_report(cache_before, _cache_metrics_snapshot(args))
    _write_json(out_dir / "vllm_response.json", response)
    _write_json(out_dir / "collect.json", collect)
    _write_json(out_dir / "cache_metrics.json", cache_metrics)
    grade_summary = grade_collect(requests_by_id, collect)
    _write_json(out_dir / "grade.json", grade_summary)
    answers = _write_direct_answers(out_dir / "answers.jsonl", requests_by_id, collect, run_s)
    _write_direct_manifest(args, out_dir, batch_id, source_requests, requests_path, requests_payload, run_s)
    summary = _run_summary(batch_id, requests_payload, answers, len(answers), run_s, 0.0, grade_summary, out_dir)
    summary.update({"mode": "direct-vllm", "vllm_url": args.vllm_url, "served_model": args.served_model})
    summary["cache_metrics"] = cache_metrics
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))


def run_direct_vllm_chat_eval(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_id = args.batch_id or f"ds4-eval-direct-chat-{uuid.uuid4().hex[:16]}"
    source_requests, requests_path, requests_payload = _prepare_run_requests(args, out_dir, batch_id)
    requests_by_id = _request_meta_by_id(requests_payload)
    cache_before = _cache_metrics_snapshot(args)
    collect, response, run_s = _run_direct_vllm_chat_batch(args, requests_payload)
    cache_metrics = _cache_metrics_report(cache_before, _cache_metrics_snapshot(args))
    _write_json(out_dir / "vllm_response.json", response)
    _write_json(out_dir / "collect.json", collect)
    _write_json(out_dir / "cache_metrics.json", cache_metrics)
    grade_summary = grade_collect(requests_by_id, collect)
    _write_json(out_dir / "grade.json", grade_summary)
    answers = _write_direct_answers(out_dir / "answers.jsonl", requests_by_id, collect, run_s)
    _write_direct_manifest(args, out_dir, batch_id, source_requests, requests_path, requests_payload, run_s)
    summary = _run_summary(batch_id, requests_payload, answers, len(answers), run_s, 0.0, grade_summary, out_dir)
    summary.update({"mode": "direct-vllm-chat", "vllm_url": args.vllm_url, "served_model": args.served_model})
    summary["cache_metrics"] = cache_metrics
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))


def _run_direct_vllm_batch(args: argparse.Namespace, requests_payload: list[dict]) -> tuple[dict, dict, float]:
    payload = _direct_completion_payload(args, requests_payload)
    started = time.time()
    response = _post_json(args.vllm_url, "/v1/completions", payload, timeout=float(args.vllm_timeout_s))
    run_s = time.time() - started
    return _direct_collect_from_completion(requests_payload, response), response, run_s


def _run_direct_vllm_chat_batch(args: argparse.Namespace, requests_payload: list[dict]) -> tuple[dict, dict, float]:
    started = time.time()
    responses: list[dict | None] = [None] * len(requests_payload)
    results: list[dict | None] = [None] * len(requests_payload)
    concurrency = max(1, int(getattr(args, "chat_concurrency", 1) or 1))

    def run_one(index: int, row: dict) -> tuple[int, dict, dict]:
        payload = _direct_chat_payload(args, row)
        response = _post_json(args.vllm_url, "/v1/chat/completions", payload, timeout=float(args.vllm_timeout_s))
        return index, response, _direct_collect_item_from_chat(row, response)

    if concurrency == 1 or len(requests_payload) <= 1:
        for idx, row in enumerate(requests_payload):
            index, response, result = run_one(idx, row)
            responses[index] = response
            results[index] = result
    else:
        workers = min(concurrency, len(requests_payload))
        with futures.ThreadPoolExecutor(max_workers=workers) as executor:
            pending = [executor.submit(run_one, idx, row) for idx, row in enumerate(requests_payload)]
            for future in futures.as_completed(pending):
                index, response, result = future.result()
                responses[index] = response
                results[index] = result
    run_s = time.time() - started
    return {"format": "ds4-eval-direct-vllm-chat-collect-v1", "results": results}, {"responses": responses}, run_s


def _direct_completion_payload(args: argparse.Namespace, requests_payload: list[dict]) -> dict:
    prompts = []
    for row in requests_payload:
        prompt = ((row.get("input") or {}).get("rendered_prompt") or "")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError(f"request {row.get('request_id')} is missing input.rendered_prompt")
        prompts.append(prompt)
    return {
        "model": args.served_model,
        "prompt": prompts,
        "max_tokens": int(args.max_output_tokens),
        "temperature": float(args.temperature),
        "stream": False,
    }


def _direct_chat_payload(args: argparse.Namespace, row: dict) -> dict:
    item = row.get("input") if isinstance(row.get("input"), dict) else {}
    messages = item.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError(f"request {row.get('request_id')} is missing input.messages")
    payload = {
        "model": args.served_model,
        "messages": messages,
        "max_tokens": int(args.max_output_tokens),
        "temperature": float(args.temperature),
        "stream": False,
        "chat_template_kwargs": {
            str(args.chat_template_thinking_key): bool(args.enable_thinking),
        },
    }
    if bool(args.enable_thinking):
        payload["thinking_token_budget"] = int(args.thinking_budget_tokens)
    return payload


def _direct_collect_from_completion(requests_payload: list[dict], response: dict) -> dict:
    choices = response.get("choices")
    if not isinstance(choices, list):
        raise ValueError(f"completion response missing choices: {response}")
    by_index = {_choice_index(choice, pos): choice for pos, choice in enumerate(choices) if isinstance(choice, dict)}
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    results = []
    for idx, row in enumerate(requests_payload):
        choice = by_index.get(idx, {})
        text = str(choice.get("text") or "") if isinstance(choice, dict) else ""
        item_usage = _direct_choice_usage(choice, usage, len(requests_payload), idx)
        request_id = str(row.get("request_id") or "")
        results.append(
            {
                "request": {"request_id": request_id, "state": "completed"},
                "result": {
                    "request_id": request_id,
                    "status": "completed",
                    "output": {"text": text},
                    "usage": item_usage,
                },
            }
        )
    return {"format": "ds4-eval-direct-vllm-collect-v1", "results": results}


def _direct_collect_item_from_chat(row: dict, response: dict) -> dict:
    choices = response.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    text = str(message.get("content") or "")
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    item_usage = {key: int(value) for key, value in usage.items() if isinstance(value, (int, float))}
    request_id = str(row.get("request_id") or "")
    return {
        "request": {"request_id": request_id, "state": "completed"},
        "result": {
            "request_id": request_id,
            "status": "completed",
            "output": {"text": text},
            "usage": item_usage,
        },
    }


def _choice_index(choice: dict, fallback: int) -> int:
    value = choice.get("index")
    return int(value) if isinstance(value, (int, float)) else fallback


def _direct_choice_usage(choice: dict, aggregate_usage: dict, count: int, index: int) -> dict:
    usage = choice.get("usage") if isinstance(choice.get("usage"), dict) else {}
    if usage:
        return {key: int(value) for key, value in usage.items() if isinstance(value, (int, float))}
    completion = _split_usage_value(aggregate_usage, "completion_tokens", count, index)
    prompt = _split_usage_value(aggregate_usage, "prompt_tokens", count, index)
    out = {"completion_tokens": completion, "prompt_tokens": prompt}
    out["total_tokens"] = prompt + completion
    return out


def _split_usage_value(usage: dict, key: str, count: int, index: int) -> int:
    value = usage.get(key)
    if not isinstance(value, (int, float)) or count <= 0:
        return 0
    whole = max(0, int(value))
    base = whole // count
    return base + (1 if index < (whole % count) else 0)


def _write_direct_answers(path: Path, requests_by_id: dict[str, dict], collect: dict, run_s: float) -> list[dict]:
    answers = []
    state = {"passed": 0, "completion_tokens": 0}
    with path.open("w", encoding="utf-8") as answer_handle:
        items = list(_collect_items_by_request_id(collect).values())
        total = len(items)
        for item in items:
            request_id = _collect_item_request_id(item)
            record = _answer_record(requests_by_id.get(request_id, {}), item, elapsed_s=run_s)
            state["passed"] += 1 if record.get("passed") else 0
            state["completion_tokens"] += int(record.get("completion_tokens", 0) or 0)
            _attach_cumulative_stats(record, len(answers) + 1, total, state["passed"], state["completion_tokens"])
            answers.append(record)
            answer_handle.write(json.dumps(record, sort_keys=True) + "\n")
            print(_answer_line(record), flush=True)
    return answers


def _write_direct_manifest(args: argparse.Namespace, out_dir: Path, batch_id: str, source_requests: Path, requests_path: Path, requests_payload: list[dict], run_s: float) -> None:
    manifest = {
        "format": "ds4-eval-direct-vllm-run-v1",
        "batch_id": batch_id,
        "vllm_url": args.vllm_url,
        "served_model": args.served_model,
        "source": _source_filters(args),
        "request_count": len(requests_payload),
        "requests_jsonl": str(requests_path),
        "source_requests_jsonl": str(source_requests),
        "run_s": round(run_s, 6),
    }
    _write_json(out_dir / "manifest.json", manifest)


def run_eval(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_id = args.batch_id or f"ds4-eval-{uuid.uuid4().hex[:16]}"
    source_requests, requests_path, requests_payload = _prepare_run_requests(args, out_dir, batch_id)
    requests_by_id = _request_meta_by_id(requests_payload)
    cache_before = _cache_metrics_snapshot(args)
    after_event_id, submit_s = _submit_eval_batch(args, out_dir, batch_id, source_requests, requests_path, requests_payload)
    run_started = time.time()
    answers, answered_ids = _poll_live_answers(args, batch_id, requests_by_id, out_dir / "answers.jsonl", after_event_id, run_started)
    run_s = time.time() - run_started
    live_answer_count = len(answers)
    status = _get_json(args.base_url, "/ds4/queue/status", {"batch_id": batch_id, "refresh": 0})
    collect = _get_json(args.base_url, "/ds4/queue/collect", {"batch_id": batch_id})
    cache_metrics = _cache_metrics_report(cache_before, _cache_metrics_snapshot(args))
    answers = _backfill_answers(collect, requests_by_id, out_dir / "answers.jsonl", run_started, answers, answered_ids)
    _write_json(out_dir / "status.json", status)
    _write_json(out_dir / "collect.json", collect)
    _write_json(out_dir / "cache_metrics.json", cache_metrics)
    grade_summary = grade_collect(requests_by_id, collect)
    _write_json(out_dir / "grade.json", grade_summary)
    summary = _run_summary(batch_id, requests_payload, answers, live_answer_count, run_s, submit_s, grade_summary, out_dir)
    summary["cache_metrics"] = cache_metrics
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))


def _prepare_run_requests(args: argparse.Namespace, out_dir: Path, batch_id: str) -> tuple[Path, Path, list[dict]]:
    source_requests = Path(args.requests_jsonl) if args.requests_jsonl else out_dir / "requests.source.jsonl"
    if not args.requests_jsonl:
        write_requests(_write_args_for_run(args, source_requests))
    requests_payload = _load_requests_jsonl(source_requests)
    requests_payload = _filter_request_payloads(requests_payload, _source_filters(args))
    if args.limit and args.requests_jsonl:
        requests_payload = requests_payload[: int(args.limit)]
    if not args.preserve_request_ids:
        requests_payload = _remap_request_ids(requests_payload, batch_id)
    requests_path = out_dir / "requests.jsonl"
    _write_requests_jsonl(requests_path, requests_payload)
    return source_requests, requests_path, requests_payload


def _write_args_for_run(args: argparse.Namespace, source_requests: Path) -> argparse.Namespace:
    return argparse.Namespace(
        source_c=args.source_c,
        out_jsonl=str(source_requests),
        vllm_url=args.vllm_url,
        served_model=args.served_model,
        model=args.model,
        max_output_tokens=args.max_output_tokens,
        response_style=args.response_style,
        enable_thinking=args.enable_thinking,
        chat_template_thinking_key=args.chat_template_thinking_key,
        thinking_budget_tokens=args.thinking_budget_tokens,
        temperature=args.temperature,
        source=args.source,
        limit=args.limit,
    )


def _submit_eval_batch(args: argparse.Namespace, out_dir: Path, batch_id: str, source_requests: Path, requests_path: Path, requests_payload: list[dict]) -> tuple[int, float]:
    after_event_id = int(_get_json(args.base_url, "/ds4/queue/status").get("newest_event_id") or 0)
    submit_started = time.time()
    payload = {"batch_id": batch_id, "priority": args.priority, "requests": requests_payload}
    submit = _post_json(args.base_url, "/ds4/queue/submit", payload)
    submit_s = time.time() - submit_started
    _write_json(out_dir / "submit.json", submit)
    _write_run_manifest(args, out_dir, batch_id, source_requests, requests_path, requests_payload, submit_started, submit_s)
    return after_event_id, submit_s


def _write_run_manifest(args: argparse.Namespace, out_dir: Path, batch_id: str, source_requests: Path, requests_path: Path, requests_payload: list[dict], submitted_at: float, submit_s: float) -> None:
    manifest = {
        "format": "ds4-eval-api-live-run-v1",
        "batch_id": batch_id,
        "base_url": args.base_url,
        "source": _source_filters(args),
        "request_count": len(requests_payload),
        "requests_jsonl": str(requests_path),
        "source_requests_jsonl": str(source_requests),
        "submitted_at": submitted_at,
        "submit_s": round(submit_s, 6),
    }
    _write_json(out_dir / "manifest.json", manifest)


def _run_summary(batch_id: str, requests_payload: list[dict], answers: list[dict], live_answer_count: int, run_s: float, submit_s: float, grade_summary: dict, out_dir: Path) -> dict:
    completion_tokens = int(grade_summary.get("completion_tokens", 0) or 0)
    return {
        "format": "ds4-eval-api-live-summary-v1",
        "batch_id": batch_id,
        "request_count": len(requests_payload),
        "completed_answers_seen_live": live_answer_count,
        "completed_answers_backfilled": len(answers) - live_answer_count,
        "run_s": round(run_s, 6),
        "submit_s": round(submit_s, 6),
        "completion_tokens": completion_tokens,
        "aggregate_completion_tok_s": round(completion_tokens / run_s, 6) if run_s > 0 else 0.0,
        "passed": grade_summary["passed"],
        "failed": grade_summary["failed"],
        "accuracy": grade_summary["accuracy"],
        "out_dir": str(out_dir),
    }


def _poll_live_answers(args: argparse.Namespace, batch_id: str, requests_by_id: dict[str, dict], answers_path: Path, after_event_id: int, run_started: float) -> tuple[list[dict], set[str]]:
    state = _new_live_state(requests_by_id, after_event_id)
    with answers_path.open("w", encoding="utf-8") as answer_handle:
        while state["pending"]:
            poll = _get_json(args.base_url, "/ds4/queue/poll", {"after_event_id": state["newest_event_id"], "limit": 500})
            state["newest_event_id"] = int(poll.get("newest_event_id") or state["newest_event_id"])
            _handle_poll_events(args, batch_id, requests_by_id, poll, answer_handle, state, run_started)
            if state["pending"]:
                _wait_or_stop(args, batch_id, state, run_started, len(requests_by_id))
    return state["answers"], state["answered_ids"]


def _new_live_state(requests_by_id: dict[str, dict], after_event_id: int) -> dict:
    return {
        "pending": set(requests_by_id),
        "answers": [],
        "answered_ids": set(),
        "passed": 0,
        "completion_tokens": 0,
        "last_progress_s": 0.0,
        "newest_event_id": after_event_id,
    }


def _handle_poll_events(args: argparse.Namespace, batch_id: str, requests_by_id: dict[str, dict], poll: dict, answer_handle, state: dict, run_started: float) -> None:
    for event in poll.get("events") or []:
        request_id = str(event.get("request_id") or "")
        if request_id not in state["pending"]:
            continue
        if _print_delta_if_requested(args, event, request_id):
            continue
        if str(event.get("state") or "") not in TERMINAL:
            continue
        row = _get_json(args.base_url, "/ds4/queue/collect", {"request_id": request_id})
        record = _answer_record(requests_by_id.get(request_id, {}), row, elapsed_s=time.time() - run_started)
        _append_answer(record, answer_handle, state, len(requests_by_id))
        if _should_abort_for_accuracy(args, len(state["answers"]), state["passed"]):
            _post_json(args.base_url, "/ds4/queue/cancel", {"batch_id": batch_id, "reason": "ds4-eval accuracy abort", "force_running": True})
            raise RuntimeError(f"aborted {batch_id}: accuracy {state['passed'] / len(state['answers']):.3f} below threshold")


def _print_delta_if_requested(args: argparse.Namespace, event: dict, request_id: str) -> bool:
    if str(event.get("event_type") or "") != "delta":
        return False
    if not args.show_deltas:
        return True
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    text = str(payload.get("text") or "")
    if text:
        print(json.dumps({"event": "delta", "request_id": request_id, "text": text}, sort_keys=True), flush=True)
    return True


def _wait_or_stop(args: argparse.Namespace, batch_id: str, state: dict, run_started: float, total: int) -> None:
    elapsed = time.time() - run_started
    if args.progress_every_s > 0 and (elapsed - state["last_progress_s"]) >= args.progress_every_s:
        status = _get_json(args.base_url, "/ds4/queue/status", {"batch_id": batch_id, "refresh": 0})
        print(_progress_line(status, len(state["answers"]), total, state["passed"], state["completion_tokens"], elapsed), flush=True)
        state["last_progress_s"] = elapsed
        if str(status.get("state")) in TERMINAL:
            state["pending"].clear()
            return
    if elapsed > args.timeout_s:
        if args.cancel_on_timeout:
            _post_json(args.base_url, "/ds4/queue/cancel", {"batch_id": batch_id, "reason": "ds4-eval timed out", "force_running": True})
        raise TimeoutError(f"batch {batch_id} did not finish in {args.timeout_s}s")
    time.sleep(args.poll_s)


def _append_answer(record: dict, answer_handle, state: dict, total: int) -> None:
    state["answers"].append(record)
    state["answered_ids"].add(str(record.get("request_id") or ""))
    state["pending"].discard(str(record.get("request_id") or ""))
    state["passed"] += 1 if record.get("passed") else 0
    state["completion_tokens"] += int(record.get("completion_tokens", 0) or 0)
    _attach_cumulative_stats(record, len(state["answers"]), total, state["passed"], state["completion_tokens"])
    answer_handle.write(json.dumps(record, sort_keys=True) + "\n")
    answer_handle.flush()
    print(_answer_line(record), flush=True)


def _attach_cumulative_stats(record: dict, completed: int, total: int, passed: int, completion_tokens: int) -> None:
    elapsed_s = float(record.get("elapsed_s") or 0.0)
    record["cumulative_completed"] = completed
    record["cumulative_total"] = total
    record["cumulative_passed"] = passed
    record["cumulative_accuracy"] = round(_running_accuracy(completed, passed), 6)
    record["cumulative_completion_tokens"] = completion_tokens
    record["cumulative_completion_tok_s"] = round(_running_tok_s(completion_tokens, elapsed_s), 6)


def _backfill_answers(collect: dict, requests_by_id: dict[str, dict], answers_path: Path, run_started: float, answers: list[dict], answered_ids: set[str]) -> list[dict]:
    state = _backfill_state(answers, answered_ids)
    with answers_path.open("a", encoding="utf-8") as answer_handle:
        for item in _collect_items_by_request_id(collect).values():
            request_id = _collect_item_request_id(item)
            if request_id in state["answered_ids"]:
                continue
            record = _answer_record(requests_by_id.get(request_id, {}), item, elapsed_s=time.time() - run_started)
            _append_answer(record, answer_handle, state, len(requests_by_id))
    return state["answers"]


def _backfill_state(answers: list[dict], answered_ids: set[str]) -> dict:
    return {
        "pending": set(),
        "answers": answers,
        "answered_ids": answered_ids,
        "passed": sum(1 for item in answers if item.get("passed")),
        "completion_tokens": sum(int(item.get("completion_tokens", 0) or 0) for item in answers),
    }


def _load_requests_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{line_no}: request must be an object")
        rows.append(item)
    if not rows:
        raise ValueError(f"{path}: no requests found")
    return rows


def _write_requests_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _cache_metrics_snapshot(args: argparse.Namespace) -> dict:
    if not bool(getattr(args, "cache_metrics", False)):
        return {"format": "ds4-eval-cache-metrics-snapshot-v1", "enabled": False}
    vllm_url = str(getattr(args, "vllm_url", "") or "")
    try:
        text = _get_text(vllm_url, "/metrics", timeout=float(getattr(args, "cache_metrics_timeout_s", 10.0) or 10.0))
    except Exception as exc:
        return {
            "format": "ds4-eval-cache-metrics-snapshot-v1",
            "enabled": True,
            "ok": False,
            "vllm_url": vllm_url,
            "error": str(exc),
        }
    metrics = _selected_cache_metrics(text)
    return {
        "format": "ds4-eval-cache-metrics-snapshot-v1",
        "enabled": True,
        "ok": True,
        "vllm_url": vllm_url,
        "selected_metric_count": len(metrics),
        "metrics": metrics,
    }


def _cache_metrics_report(before: dict, after: dict) -> dict:
    if not before.get("enabled") and not after.get("enabled"):
        return {"format": "ds4-eval-cache-metrics-report-v1", "enabled": False}
    report = {
        "format": "ds4-eval-cache-metrics-report-v1",
        "enabled": True,
        "before": before,
        "after": after,
        "delta": {},
        "changed_delta": {},
    }
    if not before.get("ok") or not after.get("ok"):
        return report
    before_metrics = before.get("metrics") if isinstance(before.get("metrics"), dict) else {}
    after_metrics = after.get("metrics") if isinstance(after.get("metrics"), dict) else {}
    keys = sorted(set(before_metrics) | set(after_metrics))
    delta = {key: round(float(after_metrics.get(key, 0.0)) - float(before_metrics.get(key, 0.0)), 6) for key in keys}
    report["delta"] = delta
    report["changed_delta"] = {key: value for key, value in delta.items() if value != 0}
    return report


def _selected_cache_metrics(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    needles = ("cache", "prefix", "kv", "prompt")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        series, value = parts
        if not any(needle in series.lower() for needle in needles):
            continue
        try:
            out[series] = float(value)
        except ValueError:
            continue
    return out


def _remap_request_ids(rows: list[dict], batch_id: str) -> list[dict]:
    out = []
    for idx, item in enumerate(rows):
        cloned = json.loads(json.dumps(item))
        cloned["request_id"] = f"{batch_id}-{idx:06d}"
        out.append(cloned)
    return out


def _request_meta_by_id(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for item in rows:
        meta = item.get("input", {}).get("metadata", {}).get("ds4_eval", {})
        out[str(item["request_id"])] = meta if isinstance(meta, dict) else {}
    return out


def _answer_record(meta: dict, row: dict, *, elapsed_s: float) -> dict:
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    text = str((result.get("output") or {}).get("text") or "")
    got, passed = _grade_one(meta, text)
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    request = row.get("request") if isinstance(row.get("request"), dict) else {}
    return {
        "elapsed_s": round(elapsed_s, 6),
        "request_id": str(request.get("request_id") or result.get("request_id") or ""),
        "index": meta.get("index"),
        "source": meta.get("source"),
        "id": meta.get("id"),
        "expected": meta.get("answer"),
        "got": got,
        "passed": bool(passed),
        "answer_marker_present": _last_answer_marker(_answer_region(text)) >= 0,
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "status": str(result.get("status") or request.get("state") or ""),
        "text": text,
        "text_preview": text[:240],
    }


def _collect_item_request_id(item: dict) -> str:
    request_row = item.get("request") if isinstance(item.get("request"), dict) else {}
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    return str(request_row.get("request_id") or result.get("request_id") or "")


def _collect_items_by_request_id(collect: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in collect.get("results", []):
        if not isinstance(item, dict):
            continue
        request_id = _collect_item_request_id(item)
        if request_id:
            out[request_id] = item
    return out


def _running_accuracy(completed: int, passed: int) -> float:
    return passed / completed if completed > 0 else 0.0


def _running_tok_s(completion_tokens: int, elapsed_s: float) -> float:
    return completion_tokens / elapsed_s if elapsed_s > 0 else 0.0


def _answer_line(record: dict) -> str:
    mark = "PASS" if record.get("passed") else "FAIL"
    elapsed_s = float(record.get("elapsed_s") or 0.0)
    completed = int(record.get("cumulative_completed") or 0)
    total = int(record.get("cumulative_total") or 0)
    accuracy = float(record.get("cumulative_accuracy") or 0.0)
    tok_s = float(record.get("cumulative_completion_tok_s") or 0.0)
    return (
        f"[{elapsed_s:>8.2f}s] {completed:03d}/{total:03d} "
        f"acc={accuracy:>6.1%} cum_tok/s={tok_s:>7.2f} {mark} "
        f"#{record.get('index')} {record.get('source')}:{record.get('id')} "
        f"got={record.get('got')} expected={record.get('expected')} "
        f"tokens={record.get('completion_tokens')} "
        f"answer_marker={'yes' if record.get('answer_marker_present') else 'no'}"
    )


def _progress_line(status: dict, completed: int, total: int, passed: int, completion_tokens: int, elapsed_s: float) -> str:
    accuracy = _running_accuracy(completed, passed)
    tok_s = _running_tok_s(completion_tokens, elapsed_s)
    state = str(status.get("state") or "unknown")
    pending = max(0, total - completed)
    return (
        f"[{elapsed_s:>8.2f}s] progress {completed:03d}/{total:03d} "
        f"pending={pending:03d} acc={accuracy:>6.1%} cum_tok/s={tok_s:>7.2f} "
        f"state={state}"
    )


def _should_abort_for_accuracy(args: argparse.Namespace, completed: int, passed: int) -> bool:
    if args.abort_after_completed <= 0 or args.abort_if_accuracy_below < 0:
        return False
    if completed < args.abort_after_completed:
        return False
    return _running_accuracy(completed, passed) < args.abort_if_accuracy_below


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.cmd == "write-requests":
        write_requests(args)
    elif args.cmd == "grade":
        grade(args)
    elif args.cmd == "run-direct-vllm":
        run_direct_vllm_eval(args)
    elif args.cmd == "run-direct-vllm-chat":
        run_direct_vllm_chat_eval(args)
    elif args.cmd == "run":
        run_eval(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write-requests")
    w.add_argument("--source-c", default=str(DEFAULT_SOURCE_C))
    w.add_argument("--out-jsonl", required=True)
    w.add_argument("--vllm-url", default="http://10.20.0.10:8102")
    w.add_argument("--served-model", default="deepseek-v4-flash-pp8")
    w.add_argument("--model", default="dsv4_vllm_mtp_pp8_smartest_v1")
    w.add_argument("--max-output-tokens", type=int, default=512)
    w.add_argument("--response-style", choices=RESPONSE_STYLES, default="official")
    w.add_argument("--enable-thinking", dest="enable_thinking", action="store_true", default=False)
    w.add_argument("--disable-thinking", dest="enable_thinking", action="store_false")
    w.add_argument("--chat-template-thinking-key", default="thinking")
    w.add_argument("--thinking-budget-tokens", type=int, default=1024)
    w.add_argument("--temperature", type=float, default=0.0)
    w.add_argument("--source", action="append", default=[], help="Only include ds4-eval cases with this source; repeat for multiple sources.")
    w.add_argument("--limit", type=int, default=0)
    g = sub.add_parser("grade")
    g.add_argument("--requests-jsonl", required=True)
    g.add_argument("--collect-json", required=True)
    g.add_argument("--out-json")
    d = sub.add_parser("run-direct-vllm")
    d.add_argument("--requests-jsonl")
    d.add_argument("--source-c", default=str(DEFAULT_SOURCE_C))
    d.add_argument("--out-dir", required=True)
    d.add_argument("--batch-id")
    d.add_argument("--preserve-request-ids", action="store_true")
    d.add_argument("--vllm-url", default="http://10.20.0.10:8102")
    d.add_argument("--served-model", default="deepseek-v4-flash-pp8")
    d.add_argument("--model", default="dsv4_vllm_mtp_pp8_smartest_v1")
    d.add_argument("--max-output-tokens", type=int, default=512)
    d.add_argument("--response-style", choices=RESPONSE_STYLES, default="official")
    d.add_argument("--enable-thinking", dest="enable_thinking", action="store_true", default=False)
    d.add_argument("--disable-thinking", dest="enable_thinking", action="store_false")
    d.add_argument("--chat-template-thinking-key", default="thinking")
    d.add_argument("--thinking-budget-tokens", type=int, default=1024)
    d.add_argument("--temperature", type=float, default=0.0)
    d.add_argument("--source", action="append", default=[], help="Only include ds4-eval cases with this source; repeat for multiple sources.")
    d.add_argument("--limit", type=int, default=0)
    d.add_argument("--vllm-timeout-s", type=float, default=3600.0)
    _add_cache_metric_args(d)
    dc = sub.add_parser("run-direct-vllm-chat")
    dc.add_argument("--requests-jsonl")
    dc.add_argument("--source-c", default=str(DEFAULT_SOURCE_C))
    dc.add_argument("--out-dir", required=True)
    dc.add_argument("--batch-id")
    dc.add_argument("--preserve-request-ids", action="store_true")
    dc.add_argument("--vllm-url", default="http://10.20.0.10:8102")
    dc.add_argument("--served-model", default="deepseek-v4-flash-pp8")
    dc.add_argument("--model", default="dsv4_vllm_mtp_pp8_smartest_v1")
    dc.add_argument("--max-output-tokens", type=int, default=512)
    dc.add_argument("--response-style", choices=RESPONSE_STYLES, default="official")
    dc.add_argument("--enable-thinking", dest="enable_thinking", action="store_true", default=False)
    dc.add_argument("--disable-thinking", dest="enable_thinking", action="store_false")
    dc.add_argument("--chat-template-thinking-key", default="thinking")
    dc.add_argument("--thinking-budget-tokens", type=int, default=1024)
    dc.add_argument("--chat-concurrency", type=int, default=1)
    dc.add_argument("--temperature", type=float, default=0.0)
    dc.add_argument("--source", action="append", default=[], help="Only include ds4-eval cases with this source; repeat for multiple sources.")
    dc.add_argument("--limit", type=int, default=0)
    dc.add_argument("--vllm-timeout-s", type=float, default=3600.0)
    _add_cache_metric_args(dc)
    r = sub.add_parser("run")
    r.add_argument("--base-url", default="http://10.20.0.10:8700")
    r.add_argument("--requests-jsonl")
    r.add_argument("--source-c", default=str(DEFAULT_SOURCE_C))
    r.add_argument("--out-dir", required=True)
    r.add_argument("--batch-id")
    r.add_argument("--preserve-request-ids", action="store_true")
    r.add_argument("--vllm-url", default="http://10.20.0.10:8102")
    r.add_argument("--served-model", default="deepseek-v4-flash-pp8")
    r.add_argument("--model", default="dsv4_vllm_mtp_pp8_smartest_v1")
    r.add_argument("--max-output-tokens", type=int, default=512)
    r.add_argument("--response-style", choices=RESPONSE_STYLES, default="official")
    r.add_argument("--enable-thinking", dest="enable_thinking", action="store_true", default=False)
    r.add_argument("--disable-thinking", dest="enable_thinking", action="store_false")
    r.add_argument("--chat-template-thinking-key", default="thinking")
    r.add_argument("--thinking-budget-tokens", type=int, default=1024)
    r.add_argument("--temperature", type=float, default=0.0)
    r.add_argument("--source", action="append", default=[], help="Only include ds4-eval cases with this source; repeat for multiple sources.")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--priority", type=int)
    r.add_argument("--timeout-s", type=float, default=1800.0)
    r.add_argument("--poll-s", type=float, default=0.05)
    r.add_argument("--progress-every-s", type=float, default=10.0)
    r.add_argument("--abort-after-completed", type=int, default=0)
    r.add_argument("--abort-if-accuracy-below", type=float, default=-1.0)
    r.add_argument("--cancel-on-timeout", dest="cancel_on_timeout", action="store_true", default=False)
    r.add_argument("--no-cancel-on-timeout", dest="cancel_on_timeout", action="store_false")
    r.add_argument("--show-deltas", action="store_true")
    _add_cache_metric_args(r)
    return parser


def _add_cache_metric_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cache-metrics", action="store_true", help="Snapshot selected vLLM /metrics cache counters before and after the eval run.")
    parser.add_argument("--cache-metrics-timeout-s", type=float, default=10.0)


if __name__ == "__main__":
    main()
