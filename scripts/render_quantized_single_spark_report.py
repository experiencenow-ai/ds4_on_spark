#!/usr/bin/env python3
"""Render a commit-ready quantized single-Spark baseline report from a local run dir.

Input is the `OUT_DIR` written by `scripts/run_baseline_existing_runtime.sh`.
This script is offline: it only reads local files already captured by the run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_kv_block(text: str, marker: str) -> Dict[str, str]:
    lines = text.splitlines()
    out: Dict[str, str] = {}
    found = False
    for raw in lines:
        line = raw.rstrip("\n")
        if not found:
            if line.strip() == marker:
                found = True
            continue
        if line.startswith("== "):
            break
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k:
            out[k] = v
    return out


def _extract_section(text: str, header: str) -> str:
    needle = f"## {header}"
    lines = text.splitlines()
    out_lines = []
    in_section = False
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("## ") and line != needle and in_section:
            break
        if line == needle:
            in_section = True
            continue
        if in_section:
            out_lines.append(line)
    return "\n".join(out_lines).strip()


def _extract_first_code_block(section_text: str) -> str:
    lines = section_text.splitlines()
    in_code = False
    out = []
    for line in lines:
        if line.strip().startswith("```") and not in_code:
            in_code = True
            continue
        if line.strip().startswith("```") and in_code:
            break
        if in_code:
            out.append(line)
    return "\n".join(out).strip()

def _extract_code_block_after(section_text: str, anchor: str) -> str:
    if not section_text:
        return ""
    pos = section_text.find(anchor)
    if pos < 0:
        return _extract_first_code_block(section_text)
    return _extract_first_code_block(section_text[pos:])

def _parse_scored_summary(scored_summary_text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    found = False
    for raw in scored_summary_text.splitlines():
        line = raw.strip()
        if not found:
            if line.startswith("== scored summary"):
                found = True
            continue
        if line.startswith("== "):
            break
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k:
            out[k] = v
    return out

def _parse_quality_metadata(report_md: str) -> Dict[str, str]:
    section = _extract_section(report_md, "Quality Metadata (Local)")
    out: Dict[str, str] = {}
    for raw in section.splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        line = line[2:].strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        if k:
            out[k] = v
    return out


def _parse_utc(remote_llama_stdout: str) -> Optional[str]:
    for line in remote_llama_stdout.splitlines():
        line = line.strip()
        if line.startswith("utc="):
            return line.split("=", 1)[1].strip()
    return None


def _parse_llama_commit(remote_llama_stdout: str) -> str:
    lines = remote_llama_stdout.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() == "== llama.cpp revision ==":
            for j in range(idx + 1, min(idx + 12, len(lines))):
                m = re.fullmatch(r"[0-9a-f]{40}", lines[j].strip())
                if m:
                    return m.group(0)
    return "unknown"


def _parse_repo_rev(report_md: str) -> str:
    m = re.search(r"ds4_on_spark commit:\s*`?([0-9a-f]{7,40}|unknown)`?", report_md)
    if m:
        return m.group(1)
    return "unknown"


def _ymd_from_utc(utc_ts: Optional[str]) -> str:
    if not utc_ts:
        return "unknown-date"
    try:
        d = dt.datetime.strptime(utc_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        return d.strftime("%Y-%m-%d")
    except ValueError:
        return "unknown-date"


def _fmt_float(v: str) -> str:
    try:
        return f"{float(v):.6f}"
    except Exception:
        return v


def _na(v: Optional[str]) -> str:
    s = (v or "").strip()
    if not s or s.upper() == "NA":
        return "NA"
    return s


def _inspect_path(inspect: Optional[Dict[str, Any]]) -> str:
    if not inspect:
        return "unknown"
    p = inspect.get("path")
    if isinstance(p, str) and p.strip():
        return p.strip()
    return "unknown"


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Render a quantized single-Spark baseline markdown report from a local OUT_DIR."
    )
    p.add_argument("out_dir", help="Output directory written by scripts/run_baseline_existing_runtime.sh")
    p.add_argument(
        "--write", dest="write_path", default="", help="Write markdown directly to this path (otherwise stdout)"
    )
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    if not out_dir.exists() or not out_dir.is_dir():
        print(f"error: out_dir does not exist or is not a directory: {out_dir}", file=sys.stderr)
        return 2

    report_md_path = out_dir / "baseline_existing_runtime.md"
    remote_llama_stdout_path = out_dir / "remote_llamacpp_stdout.txt"
    gguf_inspect_path = out_dir / "remote_gguf_inspect_stdout.txt"
    fattn_probe_path = out_dir / "remote_fattn_patch_probe_stdout.txt"
    multislot_probe_path = out_dir / "remote_multislot_patch_probe_stdout.txt"
    scored_summary_path = out_dir / "model_quality_speed_scored_summary.txt"

    report_md = _read_text(report_md_path)
    remote_llama_stdout = _read_text(remote_llama_stdout_path)
    if not remote_llama_stdout:
        print(f"error: missing remote llama stdout: {remote_llama_stdout_path}", file=sys.stderr)
        return 3

    utc_ts = _parse_utc(remote_llama_stdout)
    ymd = _ymd_from_utc(utc_ts)
    _ = ymd
    repo_rev = _parse_repo_rev(report_md)
    summary_kv = _extract_kv_block(remote_llama_stdout, "== baseline summary (approx) ==")
    llama_rev = summary_kv.get("llama_commit", "").strip() or _parse_llama_commit(remote_llama_stdout)
    runtime_label = summary_kv.get("runtime_label", "").strip() or "unknown"
    model_source = summary_kv.get("model_source", "unknown")
    model_quant = summary_kv.get("model_quant", "unknown")
    model_gguf = summary_kv.get("model_gguf", "") or _inspect_path(_read_json(gguf_inspect_path)) or "unknown"
    model_sha256 = summary_kv.get("model_sha256", "")
    model_size_bytes = summary_kv.get("model_size_bytes", "")
    llama_cli = summary_kv.get("llama_cli", "")

    ttft_s = summary_kv.get("ttft_first_output_s", summary_kv.get("ttft_s", ""))
    prefill_tps = summary_kv.get("prefill_tps", "")
    decode_tps = summary_kv.get("decode_tps", summary_kv.get("generation_tps", ""))
    total_wall_s = summary_kv.get("total_wall_s", summary_kv.get("wall_s", ""))
    output_tokens = summary_kv.get("output_tokens", "")
    max_rss_kb = summary_kv.get("max_rss_kb", "")

    inspect = _read_json(gguf_inspect_path)
    quality_kv = _parse_quality_metadata(report_md)
    scored_kv = _parse_scored_summary(_read_text(scored_summary_path))
    mtp_present = None if not inspect else bool(inspect.get("mtp_present", False))
    arch = None
    file_type = None
    block_count = None
    try:
        if inspect and isinstance(inspect.get("metadata"), dict):
            general = inspect["metadata"].get("general", {})
            if isinstance(general, dict):
                arch = general.get("architecture")
                file_type = general.get("file_type")
            deepseek4 = inspect["metadata"].get("deepseek4", {})
            if isinstance(deepseek4, dict):
                block_count = deepseek4.get("block_count")
    except Exception:
        pass

    fattn_probe = _read_json(fattn_probe_path)
    multislot_probe = _read_json(multislot_probe_path)

    # The baseline wrapper prints the remote env blocks as plain text labels followed by
    # markdown code fences (not under a dedicated "## Remote Env" section).
    remote_llama_env_block = _extract_code_block_after(report_md, "Remote llama env:")
    spark_probe_block = _extract_first_code_block(_extract_section(report_md, "Spark Probe"))

    title_suffix = model_quant if model_quant and model_quant != "unknown" else "V4 Flash"
    lines: list[str] = []
    lines.append(f"# Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash {title_suffix})")
    lines.append("")
    lines.append(f"Date (UTC): {utc_ts or 'unknown'}")
    lines.append("")
    lines.append("Baseline type:")
    lines.append("")
    lines.append("- [ ] antirez/ds4 (Mac / Metal)")
    lines.append("- [x] llama.cpp (Spark / CUDA)")
    lines.append("- [ ] vLLM (Spark / reference)")
    lines.append("- [ ] Ling 2.6 Flash target-only (Spark / vLLM or SGLang)")
    lines.append("- [ ] Qwen target-only (Spark / vLLM or SGLang)")
    lines.append("- [ ] Qwen + DFlash draft (Spark / speculative)")
    lines.append("- [ ] other target + DFlash draft (Spark / speculative)")
    lines.append("- [ ] ds4_on_spark (future)")
    lines.append("")
    lines.append("## Host")
    lines.append("")
    if spark_probe_block:
        lines.append("```text")
        lines.append(spark_probe_block)
        lines.append("```")
    else:
        lines.append("- Host probe: NA (missing from baseline_existing_runtime.md)")
    lines.append("")
    lines.append("## Repo + Upstream Revisions")
    lines.append("")
    lines.append(f"- ds4_on_spark commit: `{repo_rev}`")
    lines.append("- Upstream commit(s):")
    lines.append(f"  - llama.cpp fork: `{llama_rev}`")
    lines.append(f"  - runtime_label: `{runtime_label}`")
    if llama_cli:
        lines.append(f"  - llama_cli: `{llama_cli}`")
    lines.append("")
    lines.append("## Fixture Manifest")
    lines.append("")
    lines.append("```text")
    lines.append("Fixture:")
    lines.append("  type: gguf")
    lines.append(f"  path: {model_gguf}")
    if model_sha256:
        lines.append(f"  sha256: {model_sha256}")
    if model_size_bytes:
        lines.append(f"  size_bytes: {model_size_bytes}")
    if runtime_label and runtime_label != "unknown":
        lines.append(f"  runtime_label: {runtime_label}")
    lines.append(f"  notes: {model_source} ({model_quant})")
    lines.append("```")
    lines.append("")
    lines.append("## Command Line")
    lines.append("")
    if remote_llama_env_block:
        lines.append("Remote llama env (from baseline report):")
        lines.append("")
        lines.append("```sh")
        lines.append(remote_llama_env_block)
        lines.append("```")
    else:
        lines.append(f"- See local run dir for REMOTE_LLAMA_ENV: `{report_md_path}`")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("Quality:")
    lines.append("")
    lines.append(f"- public_quality_prior: {_na(quality_kv.get('public_quality_prior'))}")
    basis = _na(quality_kv.get("public_quality_basis"))
    source = _na(quality_kv.get("public_quality_source"))
    if basis != "NA" or source != "NA":
        lines.append(f"- public_quality_basis/source: {basis} / {source}")
    else:
        lines.append("- public_quality_basis/source: NA")
    lines.append(f"- local_quality_score: {_na(quality_kv.get('local_quality_score'))}")
    lines.append(f"- passed_tasks: {_na(quality_kv.get('passed_tasks'))}")
    lines.append(f"- total_tasks: {_na(quality_kv.get('total_tasks'))}")
    lines.append(f"- quality_score: {_na(quality_kv.get('quality_score'))}")
    lines.append("")
    lines.append("Quality/Speed scoring (from `scripts/model_quality_speed_score.py`, when available):")
    lines.append("")
    if scored_kv:
        lines.append(f"- quality_adjusted_decode_tps: `{_fmt_float(scored_kv.get('quality_adjusted_decode_tps', '')) if scored_kv.get('quality_adjusted_decode_tps') else 'NA'}`")
        lines.append(f"- correct_task_rate: `{_fmt_float(scored_kv.get('correct_task_rate', '')) if scored_kv.get('correct_task_rate') else 'NA'}`")
        lines.append(f"- tokens_per_success: `{_fmt_float(scored_kv.get('tokens_per_success', '')) if scored_kv.get('tokens_per_success') else 'NA'}`")
        lines.append(f"- dominated_by: `{scored_kv.get('dominated_by', '') or 'NA'}`")
    else:
        lines.append("- NA (missing `model_quality_speed_scored_summary.txt`; set `MODEL_RUNS_CSV` for the run)")
    lines.append("")
    lines.append("GGUF contract inspector (metadata-only):")
    lines.append("")
    if inspect:
        wks = inspect.get("weight_keys_sha256")
        if isinstance(wks, str) and wks.strip():
            lines.append(f"- weight_keys_sha256={wks.strip()}")
        mks = inspect.get("mtp_keys_sha256")
        if isinstance(mks, str) and mks.strip():
            lines.append(f"- mtp_keys_sha256={mks.strip()}")
        tns = inspect.get("tensor_key_namespace_guess")
        if isinstance(tns, str) and tns.strip():
            lines.append(f"- tensor_key_namespace_guess={tns.strip()}")
        ttop = inspect.get("topology_contract")
        if isinstance(ttop, dict):
            checked = ttop.get("checked")
            mismatches = ttop.get("mismatches")
            mismatch_count = len(mismatches) if isinstance(mismatches, list) else 0
            if checked is not None:
                lines.append(f"- topology_contract: checked={checked} mismatch_count={mismatch_count}")
                if mismatch_count and isinstance(mismatches[0], str) and mismatches[0].strip():
                    lines.append(f"- topology_contract_first_mismatch={mismatches[0].strip()}")
        tc = inspect.get("trunk_contract")
        if isinstance(tc, dict):
            kind = tc.get("kind")
            complete = tc.get("complete")
            if kind is not None or complete is not None:
                lines.append(f"- trunk_contract: kind={kind} complete={complete}")
            ne_used = tc.get("nonexpert_key_lists_used")
            ne_expected = tc.get("nonexpert_required_expected_count")
            ne_missing = tc.get("nonexpert_required_missing_count")
            if ne_expected is not None or ne_missing is not None or ne_used is not None:
                lines.append(f"- trunk_contract_nonexpert: used={ne_used} missing={ne_missing}/{ne_expected}")
        mc = inspect.get("mtp_contract")
        if isinstance(mc, dict):
            checked = mc.get("checked")
            reason = mc.get("reason")
            if checked is not None or reason is not None:
                extra = ""
                if isinstance(reason, str) and reason.strip():
                    extra = f" reason={reason.strip()}"
                lines.append(f"- mtp_contract: checked={checked}{extra}")
            ne_used = mc.get("nonexpert_key_lists_used")
            ne_expected = mc.get("nonexpert_required_expected_count")
            ne_missing = mc.get("nonexpert_required_missing_count")
            if ne_expected is not None or ne_missing is not None or ne_used is not None:
                lines.append(f"- mtp_contract_nonexpert: used={ne_used} missing={ne_missing}/{ne_expected}")
        mns = inspect.get("mtp_namespace")
        if isinstance(mns, dict):
            has_mtp0 = mns.get("has_mtp0")
            expected_complete = mns.get("expected_complete")
            present_prefixes = mns.get("present_prefixes")
            if present_prefixes is None:
                present_prefixes = []
            if has_mtp0 is not None or expected_complete is not None or present_prefixes:
                prefixes = ",".join([str(p) for p in present_prefixes]) if isinstance(present_prefixes, list) else ""
                lines.append(
                    f"- mtp_namespace: has_mtp0={has_mtp0} expected_complete={expected_complete} present_prefixes=[{prefixes}]"
                )
        mp = inspect.get("mtp_preservation")
        if isinstance(mp, dict):
            status = mp.get("status")
            match_official = mp.get("mtp_keys_sha256_match_official")
            preserves = mp.get("preserves")
            if status is not None or match_official is not None or preserves is not None:
                lines.append(f"- mtp_preservation: status={status} preserves={preserves} mtp_keys_sha256_match_official={match_official}")
        mt = inspect.get("mtp_trust")
        if isinstance(mt, dict):
            status = mt.get("status")
            trusted = mt.get("trusted")
            if status is not None or trusted is not None:
                lines.append(f"- mtp_trust: status={status} trusted={trusted}")
        qc = inspect.get("quantization_contract")
        if isinstance(qc, dict) and qc.get("checked") is not None:
            obs = qc.get("observed", {})
            if not isinstance(obs, dict):
                obs = {}
            dense = obs.get("dense_primary_type")
            expert = obs.get("expert_primary_type")
            df8 = qc.get("dense_fp8_like")
            ef4 = qc.get("expert_fp4_like")
            lines.append(f"- quantization_contract: checked={qc.get('checked')} dense={dense} expert={expert} dense_fp8_like={df8} expert_fp4_like={ef4}")
    if arch is not None or file_type is not None or block_count is not None or mtp_present is not None:
        parts = []
        if arch is not None:
            parts.append(f"general.architecture={arch}")
        if file_type is not None:
            parts.append(f"general.file_type={file_type}")
        if block_count is not None:
            parts.append(f"deepseek4.block_count={block_count}")
        if parts:
            lines.append(f"- {', '.join(parts)}")
        if mtp_present is not None:
            lines.append(f"- mtp_present={str(mtp_present).lower()}")
    else:
        lines.append("- NA (missing inspector output)")
    lines.append("")
    lines.append("Core metrics (from `== baseline summary (approx) ==`):")
    lines.append("")
    lines.append(f"- ttft_s: `{_fmt_float(ttft_s) if ttft_s else 'NA'}`")
    lines.append(f"- prefill_tps: `{_fmt_float(prefill_tps) if prefill_tps else 'NA'}`")
    lines.append(f"- decode_tps: `{_fmt_float(decode_tps) if decode_tps else 'NA'}`")
    lines.append(f"- total_wall_s: `{_fmt_float(total_wall_s) if total_wall_s else 'NA'}`")
    lines.append(f"- output_tokens: `{output_tokens if output_tokens else 'NA'}`")
    lines.append(f"- max_rss_kb: `{max_rss_kb if max_rss_kb else 'NA'}`")
    lines.append("")
    lines.append("Timing breakdown (from `llama_print_timings`, when available):")
    lines.append("")
    timing_keys = (
        "load_time_s",
        "sample_time_s",
        "prompt_eval_s",
        "eval_time_s",
        "total_time_s",
    )
    timing_present = False
    for k in timing_keys:
        if k in summary_kv:
            timing_present = True
            break
    if timing_present:
        for k in timing_keys:
            if k in summary_kv:
                lines.append(f"- {k}: `{summary_kv.get(k) or 'NA'}`")
    else:
        lines.append("- NA (timings not captured by the runtime)")
    lines.append("")
    lines.append("Flash Attention scheduling signal (from baseline summary):")
    lines.append("")
    lines.append(f"- fattn_unique_nodes: `{summary_kv.get('fattn_unique_nodes', 'NA') or 'NA'}`")
    lines.append(f"- fattn_log_lines: `{summary_kv.get('fattn_log_lines', 'NA') or 'NA'}`")
    extra_fattn_keys = (
        "fattn_id_min",
        "fattn_id_max",
        "fattn_id_missing_count",
        "fattn_expected_id_0_42_ok",
        "fattn_backend0_only",
        "fattn_cuda_device0_only",
    )
    for k in extra_fattn_keys:
        if k in summary_kv:
            lines.append(f"- {k}: `{summary_kv.get(k) or 'NA'}`")
    reserve_keys = (
        "sched_reserve_line_count",
        "sched_reserve_graph_nodes",
        "sched_reserve_graph_splits",
        "sched_reserve_took_ms",
    )
    for k in reserve_keys:
        if k in summary_kv:
            lines.append(f"- {k}: `{summary_kv.get(k) or 'NA'}`")
    if summary_kv.get("fattn_seen_disabled", ""):
        lines.append("- fattn_seen_disabled: `true`")
    if summary_kv.get("fattn_seen_sched_reserve_cpu", ""):
        lines.append("- fattn_seen_sched_reserve_cpu: `true`")
    lines.append("")
    lines.append("Patch probes (read-only):")
    lines.append("")
    if fattn_probe and isinstance(fattn_probe, dict):
        lines.append(f"- fattn_patch_probe.pad256_found={str(bool(fattn_probe.get('pad256_found', False))).lower()}")
    else:
        lines.append("- fattn_patch_probe: NA")
    if multislot_probe and isinstance(multislot_probe, dict):
        lines.append(
            f"- multislot_patch_probe.reserve_cap_n_ctx_seq_found={str(bool(multislot_probe.get('reserve_cap_n_ctx_seq_found', False))).lower()}"
        )
        lines.append(f"- multislot_patch_probe.swa_stream_view_found={str(bool(multislot_probe.get('swa_stream_view_found', False))).lower()}")
        lines.append(f"- multislot_patch_probe.reserve_bound_tokens_found={str(bool(multislot_probe.get('reserve_bound_tokens_found', False))).lower()}")
        lines.append(f"- multislot_patch_probe.skip_impossible_windows_found={str(bool(multislot_probe.get('skip_impossible_windows_found', False))).lower()}")
    else:
        lines.append("- multislot_patch_probe: NA")
    lines.append("")
    lines.append("Raw summary block:")
    lines.append("")
    lines.append("```text")
    for k, v in summary_kv.items():
        lines.append(f"{k}={v}")
    lines.append("```")
    lines.append("")

    md = "\n".join(lines)
    if args.write_path:
        out_path = Path(args.write_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(str(out_path))
        return 0

    sys.stdout.write(md)
    if not md.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
