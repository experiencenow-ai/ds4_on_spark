#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def _post_json(base_url: str, endpoint: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        base_url.rstrip("/") + endpoint,
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(base_url: str, endpoint: str, query: dict[str, object] | None = None) -> dict:
    suffix = ""
    if query:
        suffix = "?" + parse.urlencode({k: v for k, v in query.items() if v is not None})
    with request.urlopen(base_url.rstrip("/") + endpoint + suffix, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


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


def build_question_prompt(case: dict) -> str:
    parts = [case["question"] + "\n"]
    choices = case.get("choices") or []
    if choices:
        parts.append("\nChoices:\n")
        for idx, choice in enumerate(choices):
            parts.append(f"{chr(ord('A') + idx)}. {choice}\n")
        parts.append(
            "\nSolve the question. At the end, write exactly one final line in this "
            "format and do not write anything after it:\n"
            "Answer: <letter>"
        )
    elif case.get("source") == "COMPSEC":
        parts.append(
            "\nAt the end, write exactly one final line in this format and do not "
            "write anything after it:\n"
            "Answer: <line number or comma-separated line numbers>"
        )
    else:
        parts.append(
            "\nSolve the problem. At the end, write exactly one final line in this "
            "format and do not write anything after it:\n"
            "Answer: <integer>"
        )
    return "".join(parts)


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
    if enable_thinking:
        payload["chat_template_kwargs"] = {thinking_key: True}
    rendered = _post_json(vllm_url, "/v1/chat/completions/render", payload)
    token_ids = rendered.get("token_ids")
    if not isinstance(token_ids, list):
        raise ValueError(f"render endpoint did not return token_ids: {rendered}")
    detok = _post_json(vllm_url, "/detokenize", {"model": model, "tokens": token_ids})
    prompt = detok.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError(f"detokenize endpoint did not return prompt: {detok}")
    return prompt


def write_requests(args: argparse.Namespace) -> None:
    cases = parse_eval_cases(Path(args.source_c))
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
    question_prompt = build_question_prompt(case)
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
        "thinking_budget_tokens": int(args.thinking_budget_tokens),
        "temperature": float(args.temperature),
        "input": _request_input_payload(case, question_prompt, rendered, idx),
        "output_contract": {"format": "text"},
        "model_pin": {"profile_id": args.model},
    }


def _request_input_payload(case: dict, question_prompt: str, rendered: str, idx: int) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question_prompt},
        ],
        "rendered_prompt": rendered,
        "prompt": question_prompt,
        "metadata": {
            "rendered_prompt": rendered,
            "ds4_eval": _eval_metadata(case, idx),
        },
        "estimated_prompt_tokens": len(rendered.split()),
    }


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
        "requests_jsonl": str(out),
        "request_count": request_count,
        "max_output_tokens": int(args.max_output_tokens),
        "enable_thinking": bool(args.enable_thinking),
        "thinking_budget_tokens": int(args.thinking_budget_tokens),
        "temperature": float(args.temperature),
        "written_at": time.time(),
    }
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))


def _answer_region(text: str) -> str:
    pos = text.find("</think>")
    return text[pos + len("</think>") :] if pos >= 0 else text


def _last_answer_marker(text: str) -> int:
    last = -1
    for match in re.finditer(r"(?i)\banswer\b\s*:", text):
        last = match.start()
    return last


def _letter_answer(text: str, nchoices: int) -> str:
    visible = _answer_region(text)
    start = _last_answer_marker(visible)
    if start < 0:
        return "?"
    max_letter = chr(ord("A") + nchoices - 1)
    spans = [visible[start : start + 96]] if start >= 0 else []
    for span in spans:
        for match in reversed(list(re.finditer(r"\b[A-Z]\b", span.upper()))):
            letter = match.group(0)
            if "A" <= letter <= max_letter:
                return letter
    return "?"


def _integer_answer(text: str) -> str:
    visible = _answer_region(text)
    start = _last_answer_marker(visible)
    if start < 0:
        return "?"
    spans = [visible[start : start + 160]] if start >= 0 else []
    for span in spans:
        matches = re.findall(r"\d+", span)
        if matches:
            return str(int(matches[-1]))
    return "?"


def _line_spec(text: str) -> str:
    visible = _answer_region(text)
    start = _last_answer_marker(visible)
    if start < 0:
        return "?"
    span = visible[start : start + 160] if start >= 0 else visible
    pieces = re.findall(r"\d+(?:\s*-\s*\d+)?", span)
    return ",".join(piece.replace(" ", "") for piece in pieces) if pieces else "?"


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


def run_eval(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_id = args.batch_id or f"ds4-eval-{uuid.uuid4().hex[:16]}"
    source_requests, requests_path, requests_payload = _prepare_run_requests(args, out_dir, batch_id)
    requests_by_id = _request_meta_by_id(requests_payload)
    after_event_id, submit_s = _submit_eval_batch(args, out_dir, batch_id, source_requests, requests_path, requests_payload)
    run_started = time.time()
    answers, answered_ids = _poll_live_answers(args, batch_id, requests_by_id, out_dir / "answers.jsonl", after_event_id, run_started)
    run_s = time.time() - run_started
    live_answer_count = len(answers)
    status = _get_json(args.base_url, "/ds4/queue/status", {"batch_id": batch_id, "refresh": 0})
    collect = _get_json(args.base_url, "/ds4/queue/collect", {"batch_id": batch_id})
    answers = _backfill_answers(collect, requests_by_id, out_dir / "answers.jsonl", run_started, answers, answered_ids)
    _write_json(out_dir / "status.json", status)
    _write_json(out_dir / "collect.json", collect)
    grade_summary = grade_collect(requests_by_id, collect)
    _write_json(out_dir / "grade.json", grade_summary)
    summary = _run_summary(batch_id, requests_payload, answers, live_answer_count, run_s, submit_s, grade_summary, out_dir)
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))


def _prepare_run_requests(args: argparse.Namespace, out_dir: Path, batch_id: str) -> tuple[Path, Path, list[dict]]:
    source_requests = Path(args.requests_jsonl) if args.requests_jsonl else out_dir / "requests.source.jsonl"
    if not args.requests_jsonl:
        write_requests(_write_args_for_run(args, source_requests))
    requests_payload = _load_requests_jsonl(source_requests)
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
        enable_thinking=args.enable_thinking,
        chat_template_thinking_key=args.chat_template_thinking_key,
        thinking_budget_tokens=args.thinking_budget_tokens,
        temperature=args.temperature,
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
    w.add_argument("--enable-thinking", dest="enable_thinking", action="store_true", default=True)
    w.add_argument("--disable-thinking", dest="enable_thinking", action="store_false")
    w.add_argument("--chat-template-thinking-key", default="thinking")
    w.add_argument("--thinking-budget-tokens", type=int, default=1024)
    w.add_argument("--temperature", type=float, default=0.0)
    w.add_argument("--limit", type=int, default=0)
    g = sub.add_parser("grade")
    g.add_argument("--requests-jsonl", required=True)
    g.add_argument("--collect-json", required=True)
    g.add_argument("--out-json")
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
    r.add_argument("--enable-thinking", dest="enable_thinking", action="store_true", default=True)
    r.add_argument("--disable-thinking", dest="enable_thinking", action="store_false")
    r.add_argument("--chat-template-thinking-key", default="thinking")
    r.add_argument("--thinking-budget-tokens", type=int, default=1024)
    r.add_argument("--temperature", type=float, default=0.0)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--priority", type=int)
    r.add_argument("--timeout-s", type=float, default=1800.0)
    r.add_argument("--poll-s", type=float, default=0.05)
    r.add_argument("--progress-every-s", type=float, default=10.0)
    r.add_argument("--abort-after-completed", type=int, default=0)
    r.add_argument("--abort-if-accuracy-below", type=float, default=-1.0)
    r.add_argument("--cancel-on-timeout", dest="cancel_on_timeout", action="store_true", default=True)
    r.add_argument("--no-cancel-on-timeout", dest="cancel_on_timeout", action="store_false")
    r.add_argument("--show-deltas", action="store_true")
    return parser


if __name__ == "__main__":
    main()
