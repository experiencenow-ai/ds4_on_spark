#!/usr/bin/env python3
"""Run antirez ds4-eval cases through a pipeline-compatible generator."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shlex
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FORMAT = "pipeline-quality-regression-v1"
SYSTEM_PROMPT = "You are solving a hard benchmark question. Reason carefully. The final answer must follow the requested format exactly."


@dataclass(frozen=True)
class EvalCase:
	source: str
	case_id: str
	domain: str
	title: str
	question: str
	choices: tuple[str, ...]
	answer: str


@dataclass(frozen=True)
class GenerationResult:
	text: str
	token_ids: list[int]
	elapsed_sec: float
	raw_stdout: str
	raw_stderr: str
	returncode: int


def sha256_text(text: str) -> str:
	return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path: Path) -> str:
	return path.read_text(encoding="utf-8")


def _c_string_value(expr: str) -> str:
	parts = re.findall(r'"(?:\\.|[^"\\])*"', expr, flags=re.S)
	if not parts:
		return ""
	return "".join(str(ast.literal_eval(part)) for part in parts)


def _find_eval_cases_body(source: str) -> str:
	marker = "static const eval_case eval_cases[]"
	start = source.find(marker)
	if start < 0:
		raise ValueError("ds4_eval.c eval_cases array not found")
	open_brace = source.find("{", start)
	if open_brace < 0:
		raise ValueError("ds4_eval.c eval_cases opening brace not found")
	depth = 0
	in_string = False
	escape = False
	for index in range(open_brace, len(source)):
		ch = source[index]
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
				return source[open_brace + 1:index]
	raise ValueError("ds4_eval.c eval_cases closing brace not found")


def _split_case_blocks(body: str) -> list[str]:
	blocks: list[str] = []
	depth = 0
	in_string = False
	escape = False
	block_start: int | None = None
	for index, ch in enumerate(body):
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
			if depth == 0:
				block_start = index + 1
			depth += 1
		elif ch == "}":
			depth -= 1
			if depth == 0 and block_start is not None:
				blocks.append(body[block_start:index])
				block_start = None
	if depth != 0:
		raise ValueError("unbalanced eval_cases initializer")
	return blocks


def load_eval_cases(path: Path, limit: int = 0) -> list[EvalCase]:
	source = _read(path)
	body = _find_eval_cases_body(source)
	cases: list[EvalCase] = []
	for block in _split_case_blocks(body):
		fields: dict[str, str] = {}
		for name in ("source", "id", "domain", "title", "question", "answer"):
			match = re.search(rf"\.{name}\s*=\s*((?:\"(?:\\.|[^\"\\])*\"\s*)+)", block, flags=re.S)
			if match:
				fields[name] = _c_string_value(match.group(1))
		choices: dict[int, str] = {}
		for match in re.finditer(r"\.choice\[(\d+)\]\s*=\s*((?:\"(?:\\.|[^\"\\])*\"\s*)+)", block, flags=re.S):
			choices[int(match.group(1))] = _c_string_value(match.group(2))
		if not fields.get("id") or not fields.get("question") or not fields.get("answer"):
			raise ValueError("malformed eval case in ds4_eval.c")
		ordered = tuple(choices[index] for index in sorted(choices))
		cases.append(EvalCase(
			source=fields.get("source", ""),
			case_id=fields["id"],
			domain=fields.get("domain", ""),
			title=fields.get("title", ""),
			question=fields["question"],
			choices=ordered,
			answer=fields["answer"],
		))
		if limit > 0 and len(cases) >= limit:
			break
	return cases


def is_compsec(case: EvalCase) -> bool:
	return case.source == "COMPSEC"


def build_question_prompt(case: EvalCase) -> str:
	pieces = [case.question, ""]
	if case.choices:
		pieces.append("Choices:")
		for index, choice in enumerate(case.choices):
			pieces.append(f"{chr(ord('A') + index)}. {choice}")
		pieces.append("")
		pieces.append("Solve the question. At the end, write exactly one final line in this format and do not write anything after it:")
		pieces.append("Answer: <letter>")
	elif is_compsec(case):
		pieces.append("At the end, write exactly one final line in this format and do not write anything after it:")
		pieces.append("Answer: <line number or comma-separated line numbers>")
	else:
		pieces.append("Solve the problem. At the end, write exactly one final line in this format and do not write anything after it:")
		pieces.append("Answer: <integer>")
	return "\n".join(pieces)


def build_rendered_prompt(case: EvalCase) -> str:
	return SYSTEM_PROMPT + "\n\n" + build_question_prompt(case)


def _visible_answer_text(generated: str) -> str:
	pos = generated.find("</think>")
	return generated[pos + len("</think>"):] if pos >= 0 else generated


def _letter_boundary(before: str, after: str) -> bool:
	return not before.isalpha() and not after.isalpha()


def find_answer_letter(generated: str, nchoices: int) -> str:
	if nchoices <= 0:
		return "?"
	visible = _visible_answer_text(generated)
	max_answer = chr(ord("A") + nchoices - 1)
	answer_pos = visible.lower().find("answer")
	if answer_pos >= 0:
		window = visible[answer_pos:answer_pos + 96]
		for offset, ch in enumerate(window):
			c = ch.upper()
			if "A" <= c <= max_answer:
				before = visible[answer_pos + offset - 1] if answer_pos + offset > 0 else " "
				after = visible[answer_pos + offset + 1] if answer_pos + offset + 1 < len(visible) else "\0"
				if _letter_boundary(before, after):
					return c
	for pos in range(len(visible) - 1, -1, -1):
		c = visible[pos].upper()
		if "A" <= c <= max_answer:
			before = visible[pos - 1] if pos > 0 else " "
			after = visible[pos + 1] if pos + 1 < len(visible) else "\0"
			if _letter_boundary(before, after):
				return c
	return "?"


def _normalize_integer(text: str) -> str:
	stripped = text.lstrip("0")
	return stripped if stripped else "0"


def _scan_first_integer(text: str) -> str | None:
	match = re.search(r"\d+", text)
	return _normalize_integer(match.group(0)) if match else None


def find_integer_answer(generated: str) -> str:
	visible = _visible_answer_text(generated)
	answer_pos = visible.lower().find("answer")
	if answer_pos >= 0:
		found = _scan_first_integer(visible[answer_pos:answer_pos + 160])
		if found is not None:
			return found
	matches = list(re.finditer(r"\d+", visible))
	return _normalize_integer(matches[-1].group(0)) if matches else "?"


def normalize_compsec_line_spec(text: str) -> str:
	values: list[str] = []
	for match in re.finditer(r"\d+(?:\s*-\s*\d+)?", text):
		values.append(re.sub(r"\s+", "", match.group(0)))
	return ",".join(values) if values else "?"


def find_compsec_answer(generated: str) -> str:
	visible = _visible_answer_text(generated)
	answer_pos = visible.lower().find("answer")
	if answer_pos >= 0:
		window = visible[answer_pos:answer_pos + 160]
		window = window.splitlines()[0] if "\n" in window else window
		got = normalize_compsec_line_spec(window)
		if got != "?":
			return got
	return find_integer_answer(generated)


def _parse_line_set(spec: str) -> set[int]:
	found: set[int] = set()
	for match in re.finditer(r"\d+(?:\s*-\s*\d+)?", spec):
		raw = match.group(0)
		if "-" in raw:
			left, right = raw.split("-", 1)
			a = int(left.strip())
			b = int(right.strip())
			if a > b:
				a, b = b, a
			found.update(range(max(0, a), min(255, b) + 1))
		else:
			value = int(raw)
			if 0 <= value <= 255:
				found.add(value)
	return found


def compsec_answer_matches(expected_spec: str, got_spec: str) -> bool:
	expected = _parse_line_set(expected_spec)
	got = _parse_line_set(got_spec)
	return bool(expected and got and got.issubset(expected))


def pick_answer(case: EvalCase, generated: str) -> str:
	if case.choices:
		return find_answer_letter(generated, len(case.choices))
	if is_compsec(case):
		return find_compsec_answer(generated)
	return find_integer_answer(generated)


def answer_matches(case: EvalCase, observed: str, generated: str) -> bool:
	if case.source == "LONG_CONTEXT_RECALL":
		return case.answer.lower() in generated.lower()
	if case.choices:
		return bool(observed and observed[0] == case.answer[0])
	if is_compsec(case):
		return compsec_answer_matches(case.answer, observed)
	return observed == _normalize_integer(case.answer)


def _last_json_object(stdout: str) -> dict[str, Any] | None:
	for text in (stdout.strip(), *reversed([line.strip() for line in stdout.splitlines() if line.strip()])):
		try:
			obj = json.loads(text)
		except json.JSONDecodeError:
			continue
		if isinstance(obj, dict):
			return obj
	return None


def _parse_token_ids(stdout: str) -> list[int]:
	match = re.search(r"token[_ -]?ids?\s*[:=]\s*(\[[^\]]*\])", stdout, flags=re.I)
	if not match:
		return []
	try:
		value = json.loads(match.group(1))
	except json.JSONDecodeError:
		return []
	if isinstance(value, list) and all(isinstance(item, int) for item in value):
		return value
	return []


def _text_from_command_output(stdout: str, obj: dict[str, Any] | None) -> str:
	if obj is not None:
		for key in ("text", "generated_text", "output_text", "response", "completion"):
			value = obj.get(key)
			if isinstance(value, str):
				return value
	lines = [line for line in stdout.splitlines() if not re.search(r"token[_ -]?ids?\s*[:=]", line, flags=re.I)]
	return "\n".join(lines).strip()


def generation_from_stdout(stdout: str, stderr: str, elapsed_sec: float, returncode: int) -> GenerationResult:
	obj = _last_json_object(stdout)
	token_ids: list[int] = []
	if obj is not None:
		raw_ids = obj.get("token_ids") or obj.get("tokens") or obj.get("committed_token_ids")
		if isinstance(raw_ids, list) and all(isinstance(item, int) for item in raw_ids):
			token_ids = list(raw_ids)
	if not token_ids:
		token_ids = _parse_token_ids(stdout)
	if obj is not None and isinstance(obj.get("elapsed_sec"), (int, float)):
		elapsed_sec = float(obj["elapsed_sec"])
	text = _text_from_command_output(stdout, obj)
	return GenerationResult(text=text, token_ids=token_ids, elapsed_sec=elapsed_sec, raw_stdout=stdout, raw_stderr=stderr, returncode=returncode)


def run_command(command_template: str, prompt: str, case: EvalCase, max_tokens: int) -> GenerationResult:
	with tempfile.TemporaryDirectory() as tmp:
		root = Path(tmp)
		prompt_file = root / "prompt.txt"
		prompt_json = root / "prompt.json"
		prompt_file.write_text(prompt, encoding="utf-8")
		prompt_json.write_text(json.dumps({"prompt": prompt, "max_tokens": max_tokens, "case_id": case.case_id}, sort_keys=True), encoding="utf-8")
		values = {
			"prompt_file": str(prompt_file),
			"prompt_json": str(prompt_json),
			"prompt": prompt,
			"max_tokens": str(max_tokens),
			"case_id": case.case_id,
		}
		argv = [part.format(**values) for part in shlex.split(command_template)]
		start = time.perf_counter()
		proc = subprocess.run(argv, text=True, capture_output=True, check=False)
		elapsed = time.perf_counter() - start
		return generation_from_stdout(proc.stdout, proc.stderr, elapsed, proc.returncode)


def run_http(url: str, prompt: str, case: EvalCase, max_tokens: int, timeout: float) -> GenerationResult:
	payload = json.dumps({"prompt": prompt, "max_tokens": max_tokens, "temperature": 0, "case_id": case.case_id}).encode("utf-8")
	req = urllib.request.Request(url, data=payload, headers={"content-type": "application/json"}, method="POST")
	start = time.perf_counter()
	with urllib.request.urlopen(req, timeout=timeout) as resp:
		stdout = resp.read().decode("utf-8")
	elapsed = time.perf_counter() - start
	return generation_from_stdout(stdout, "", elapsed, 0)


def load_baseline(path: Path | None) -> dict[str, dict[str, Any]]:
	if path is None:
		return {}
	rows: dict[str, dict[str, Any]] = {}
	for line in path.read_text(encoding="utf-8").splitlines():
		if not line.strip():
			continue
		obj = json.loads(line)
		if isinstance(obj, dict) and obj.get("record_type") == "question":
			rows[str(obj.get("case_id"))] = obj
	return rows


def baseline_delta(record: dict[str, Any], baseline: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
	base = baseline.get(str(record.get("case_id")))
	if not base:
		return None
	same_tokens = base.get("token_ids") == record.get("token_ids")
	if bool(base.get("passed")) == bool(record.get("passed")) and same_tokens:
		status = "same"
	elif bool(base.get("passed")) and not bool(record.get("passed")):
		status = "pass_to_fail"
	elif not bool(base.get("passed")) and bool(record.get("passed")):
		status = "fail_to_pass"
	else:
		status = "token_divergence" if not same_tokens else "answer_changed"
	return {
		"baseline_passed": bool(base.get("passed")),
		"baseline_observed_answer": base.get("observed_answer"),
		"baseline_token_ids": base.get("token_ids", []),
		"delta_status": status,
		"token_ids_match": same_tokens,
	}


def summarize_domains(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
	buckets: dict[tuple[str, str], dict[str, Any]] = {}
	for row in records:
		source = str(row.get("source") or "")
		domain = str(row.get("domain") or "")
		key = (source, domain)
		bucket = buckets.setdefault(key, {
			"source": source,
			"domain": domain,
			"question_count": 0,
			"passed": 0,
			"failed": 0,
			"generated_tokens": 0,
			"elapsed_sec": 0.0,
		})
		bucket["question_count"] += 1
		if row.get("passed") is True:
			bucket["passed"] += 1
		elif row.get("passed") is False:
			bucket["failed"] += 1
		bucket["generated_tokens"] += int(row.get("generated_tokens") or 0)
		bucket["elapsed_sec"] += float(row.get("elapsed_sec") or 0.0)
	breakdown = []
	for bucket in buckets.values():
		questions = int(bucket["question_count"])
		elapsed = float(bucket["elapsed_sec"])
		tokens = int(bucket["generated_tokens"])
		bucket["pass_rate"] = bucket["passed"] / questions if questions > 0 else 0.0
		bucket["aggregate_output_tokens_per_s"] = tokens / elapsed if elapsed > 0 else 0.0
		breakdown.append(bucket)
	return sorted(breakdown, key=lambda item: (str(item["source"]), str(item["domain"])))


def _parse_trace_fields(section: str) -> dict[str, str]:
	fields: dict[str, str] = {}
	for line in section.splitlines():
		if not line or line.startswith(" ") or line.startswith("#"):
			continue
		if ":" not in line:
			continue
		key, value = line.split(":", 1)
		if re.match(r"^[A-Za-z0-9_]+$", key):
			fields[key] = value.strip()
	return fields


def _trace_model_output(section: str) -> str:
	begin = re.search(r"^MODEL_OUTPUT_BEGIN bytes=\d+\s*$", section, flags=re.M)
	if not begin:
		return ""
	content_start = section.find("\n", begin.end())
	if content_start < 0:
		return ""
	content_start += 1
	end = re.search(r"^MODEL_OUTPUT_END\s*$", section[content_start:], flags=re.M)
	if not end:
		return section[content_start:].rstrip("\n")
	return section[content_start:content_start + end.start()].rstrip("\n")


def _question_kind_from_trace(source: str, section: str) -> str:
	if source == "COMPSEC":
		return "compsec"
	if re.search(r"^choices:\s*$", section, flags=re.M):
		return "multiple_choice"
	return "exact_integer"


def _int_field(fields: dict[str, str], name: str) -> int:
	try:
		return int(fields.get(name, "0"))
	except ValueError:
		return 0


def _float_field(fields: dict[str, str], name: str) -> float:
	try:
		return float(fields.get(name, "0"))
	except ValueError:
		return 0.0


def _optional_rc(path_text: str) -> int | None:
	if not path_text:
		return None
	text = Path(path_text).read_text(encoding="utf-8").strip()
	if not re.match(r"^-?\d+$", text):
		raise ValueError(f"{path_text}: rc file must contain one integer")
	return int(text)


def load_ds4_eval_trace(path: Path, args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
	text = path.read_text(encoding="utf-8")
	case_headers = list(re.finditer(r"^===== CASE (\d+)/(\d+) (.+) =====\s*$", text, flags=re.M))
	if not case_headers:
		raise ValueError(f"{path}: no ds4-eval case records found")
	header_fields = _parse_trace_fields(text[:case_headers[0].start()])
	trace_artifact = args.ds4_eval_trace_artifact or str(path)
	rc_artifact = args.ds4_eval_rc_artifact or args.ds4_eval_rc
	returncode = _optional_rc(args.ds4_eval_rc)
	records: list[dict[str, Any]] = []
	baseline = load_baseline(Path(args.baseline) if args.baseline else None)
	total_tokens = 0
	total_elapsed = 0.0
	passed = 0
	failed = 0
	started_unix = _int_field(header_fields, "started_unix")
	first_case_started_unix = 0
	last_case_started_unix = 0
	last_case_completed_unix = 0.0
	for pos, header in enumerate(case_headers):
		section_start = header.end()
		section_end = case_headers[pos + 1].start() if pos + 1 < len(case_headers) else text.find("===== SUMMARY =====", section_start)
		if section_end < 0:
			section_end = len(text)
		section = text[section_start:section_end]
		label = header.group(3)
		source, case_id = label.rsplit("/", 1) if "/" in label else ("", label)
		fields = _parse_trace_fields(section)
		status = fields.get("status", "UNKNOWN")
		ok = status == "PASSED"
		generated = _trace_model_output(section)
		prompt_tokens = _int_field(fields, "prompt_tokens")
		generated_tokens = _int_field(fields, "generated_tokens")
		elapsed_sec = _float_field(fields, "elapsed_sec")
		timestamp_unix = _int_field(fields, "timestamp_unix")
		if first_case_started_unix == 0 and timestamp_unix > 0:
			first_case_started_unix = timestamp_unix
		last_case_started_unix = max(last_case_started_unix, timestamp_unix)
		if timestamp_unix > 0:
			last_case_completed_unix = max(last_case_completed_unix, timestamp_unix + elapsed_sec)
		total_tokens += generated_tokens
		total_elapsed += elapsed_sec
		passed += 1 if ok else 0
		failed += 0 if ok else 1
		record = {
			"format": FORMAT,
			"record_type": "question",
			"run_id": args.run_id,
			"backend_mode": args.backend_mode,
			"runner_id": args.runner_id,
			"case_index": int(header.group(1)),
			"case_count": int(header.group(2)),
			"source": fields.get("source", source),
			"case_id": fields.get("id", case_id),
			"domain": fields.get("domain", ""),
			"title": fields.get("title", ""),
			"question_kind": _question_kind_from_trace(fields.get("source", source), section),
			"expected_answer": fields.get("expected", ""),
			"observed_answer": fields.get("picked", "?"),
			"passed": ok,
			"ds4_eval_status": status,
			"prompt_sha256": sha256_text(fields.get("source", source) + "/" + fields.get("id", case_id)),
			"output_sha256": sha256_text(generated),
			"generated_text": generated,
			"token_ids": [],
			"prompt_tokens": prompt_tokens,
			"generated_tokens": generated_tokens,
			"elapsed_sec": elapsed_sec,
			"output_tokens_per_s": generated_tokens / elapsed_sec if elapsed_sec > 0 else 0.0,
			"coordinator": {
				"kind": "ds4-eval-trace",
				"trace_path": trace_artifact,
				"stdout_path": args.ds4_eval_stdout,
				"command": args.ds4_eval_command,
			},
		}
		delta = baseline_delta(record, baseline)
		if delta is not None:
			record["baseline_delta"] = delta
		records.append(record)
	summary = {
		"format": FORMAT,
		"record_type": "summary",
		"run_id": args.run_id,
		"backend_mode": args.backend_mode,
		"runner_id": args.runner_id,
		"question_count": len(records),
		"passed": passed,
		"failed": failed,
		"generated_tokens": total_tokens,
		"elapsed_sec": total_elapsed,
		"aggregate_output_tokens_per_s": total_tokens / total_elapsed if total_elapsed > 0 else 0.0,
		"domain_breakdown": summarize_domains(records),
		"trace_started_unix": started_unix,
		"first_case_started_unix": first_case_started_unix,
		"last_case_started_unix": last_case_started_unix,
		"last_case_completed_unix": last_case_completed_unix,
		"trace_wall_elapsed_sec": last_case_completed_unix - started_unix if started_unix > 0 and last_case_completed_unix > 0 else 0.0,
		"startup_elapsed_sec": first_case_started_unix - started_unix if started_unix > 0 and first_case_started_unix > 0 else 0,
		"ds4_eval_returncode": returncode,
		"ds4_eval_rc_path": rc_artifact,
		"baseline_path": args.baseline or "",
		"ds4_eval_trace_path": trace_artifact,
		"ds4_eval_stdout_path": args.ds4_eval_stdout,
		"ds4_eval_command": args.ds4_eval_command,
	}
	return records, summary


def build_long_context_case(path: Path | None, repeat: int, answer: str) -> EvalCase:
	base = path.read_text(encoding="utf-8") if path else "Long context filler.\n"
	if repeat > 1:
		base = base * repeat
	question = base + f"\n\nHidden recall code: {answer}\n\nReturn only the hidden recall code from above.\nAnswer:"
	return EvalCase("LONG_CONTEXT_RECALL", "long-context-recall", "Recall", "long context recall", question, (), answer)


def run_cases(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
	cases = load_eval_cases(Path(args.ds4_eval_source), args.questions)
	if args.include_long_context:
		cases.append(build_long_context_case(Path(args.long_context_file) if args.long_context_file else None, args.long_context_repeat, args.long_context_answer))
	baseline = load_baseline(Path(args.baseline) if args.baseline else None)
	records: list[dict[str, Any]] = []
	total_tokens = 0
	total_elapsed = 0.0
	passed = 0
	failed = 0
	for index, case in enumerate(cases, start=1):
		prompt = build_rendered_prompt(case)
		if args.http_url:
			result = run_http(args.http_url, prompt, case, args.max_tokens, args.http_timeout)
			coordinator = {"kind": "http", "url": args.http_url}
		else:
			result = run_command(args.command, prompt, case, args.max_tokens)
			coordinator = {"kind": "command", "command": args.command}
		if result.returncode != 0:
			raise RuntimeError(f"generation command failed for {case.case_id}: rc={result.returncode} stderr={result.raw_stderr.strip()}")
		observed = pick_answer(case, result.text)
		ok = answer_matches(case, observed, result.text)
		generated_tokens = len(result.token_ids)
		if generated_tokens == 0:
			generated_tokens = max(1, len(result.text.split()))
		total_tokens += generated_tokens
		total_elapsed += result.elapsed_sec
		passed += 1 if ok else 0
		failed += 0 if ok else 1
		record = {
			"format": FORMAT,
			"record_type": "question",
			"run_id": args.run_id,
			"backend_mode": args.backend_mode,
			"runner_id": args.runner_id,
			"case_index": index,
			"case_count": len(cases),
			"source": case.source,
			"case_id": case.case_id,
			"domain": case.domain,
			"title": case.title,
			"question_kind": "multiple_choice" if case.choices else ("compsec" if is_compsec(case) else ("exact_text" if case.source == "LONG_CONTEXT_RECALL" else "exact_integer")),
			"expected_answer": case.answer,
			"observed_answer": observed,
			"passed": ok,
			"prompt_sha256": sha256_text(prompt),
			"output_sha256": sha256_text(result.text),
			"generated_text": result.text,
			"token_ids": result.token_ids,
			"generated_tokens": generated_tokens,
			"elapsed_sec": result.elapsed_sec,
			"output_tokens_per_s": generated_tokens / result.elapsed_sec if result.elapsed_sec > 0 else 0.0,
			"coordinator": coordinator,
		}
		delta = baseline_delta(record, baseline)
		if delta is not None:
			record["baseline_delta"] = delta
		records.append(record)
	summary = {
		"format": FORMAT,
		"record_type": "summary",
		"run_id": args.run_id,
		"backend_mode": args.backend_mode,
		"runner_id": args.runner_id,
		"question_count": len(cases),
		"passed": passed,
		"failed": failed,
		"generated_tokens": total_tokens,
		"elapsed_sec": total_elapsed,
		"aggregate_output_tokens_per_s": total_tokens / total_elapsed if total_elapsed > 0 else 0.0,
		"domain_breakdown": summarize_domains(records),
		"baseline_path": args.baseline or "",
	}
	return records, summary


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
	ap = argparse.ArgumentParser()
	ap.add_argument("--ds4-eval-source", default="")
	ap.add_argument("--ds4-eval-trace", default="")
	ap.add_argument("--ds4-eval-trace-artifact", default="")
	ap.add_argument("--ds4-eval-stdout", default="")
	ap.add_argument("--ds4-eval-rc", default="")
	ap.add_argument("--ds4-eval-rc-artifact", default="")
	ap.add_argument("--ds4-eval-command", default="")
	ap.add_argument("--command", default="")
	ap.add_argument("--http-url", default="")
	ap.add_argument("--http-timeout", type=float, default=600.0)
	ap.add_argument("--questions", type=int, default=0)
	ap.add_argument("--max-tokens", type=int, default=512)
	ap.add_argument("--run-id", default="pipeline-quality-regression")
	ap.add_argument("--runner-id", default="pipeline-quality-runner")
	ap.add_argument("--backend-mode", default="pp1", choices=("pp1", "ppn", "pipeline", "other"))
	ap.add_argument("--baseline", default="")
	ap.add_argument("--out", required=True)
	ap.add_argument("--summary-out", default="")
	ap.add_argument("--include-long-context", action="store_true")
	ap.add_argument("--long-context-file", default="")
	ap.add_argument("--long-context-repeat", type=int, default=1)
	ap.add_argument("--long-context-answer", default="LANE-D-RECALL-CODE-7429")
	ap.add_argument("--fail-on-question-failure", action="store_true")
	return ap


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	if args.ds4_eval_trace:
		if args.command or args.http_url:
			raise SystemExit("--ds4-eval-trace cannot be combined with --command or --http-url")
		records, summary = load_ds4_eval_trace(Path(args.ds4_eval_trace), args)
	elif bool(args.command) == bool(args.http_url):
		raise SystemExit("provide exactly one of --command or --http-url")
	else:
		if not args.ds4_eval_source:
			raise SystemExit("--ds4-eval-source is required without --ds4-eval-trace")
		records, summary = run_cases(args)
	rows = records + [summary]
	write_jsonl(Path(args.out), rows)
	if args.summary_out:
		Path(args.summary_out).parent.mkdir(parents=True, exist_ok=True)
		Path(args.summary_out).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	print(json.dumps(summary, sort_keys=True))
	if args.fail_on_question_failure and summary["failed"]:
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
