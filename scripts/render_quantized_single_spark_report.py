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

    report_md = _read_text(report_md_path)
    remote_llama_stdout = _read_text(remote_llama_stdout_path)
    if not remote_llama_stdout:
        print(f"error: missing remote llama stdout: {remote_llama_stdout_path}", file=sys.stderr)
        return 3

    utc_ts = _parse_utc(remote_llama_stdout)
    ymd = _ymd_from_utc(utc_ts)
    _ = ymd
    repo_rev = _parse_repo_rev(report_md)
    llama_rev = _parse_llama_commit(remote_llama_stdout)

    summary_kv = _extract_kv_block(remote_llama_stdout, "== baseline summary (approx) ==")
    model_source = summary_kv.get("model_source", "unknown")
    model_quant = summary_kv.get("model_quant", "unknown")
    model_gguf = summary_kv.get("model_gguf", "unknown")
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

    remote_env_section = _extract_section(report_md, "Remote Env")
    remote_llama_env_block = _extract_code_block_after(remote_env_section, "Remote llama.cpp env:")
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
    lines.append("- Public quality prior: NA")
    lines.append("- Public quality basis/source: NA")
    lines.append("- Local quality score: NA")
    lines.append("- Passed tasks: NA")
    lines.append("- Total tasks: NA")
    lines.append("- Quality score: NA")
    lines.append("")
    lines.append("GGUF contract inspector (metadata-only):")
    lines.append("")
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
    lines.append("Flash Attention scheduling signal (from baseline summary):")
    lines.append("")
    lines.append(f"- fattn_unique_nodes: `{summary_kv.get('fattn_unique_nodes', 'NA') or 'NA'}`")
    lines.append(f"- fattn_log_lines: `{summary_kv.get('fattn_log_lines', 'NA') or 'NA'}`")
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
