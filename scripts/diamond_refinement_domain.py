#!/usr/bin/env python3
"""Phase-A diamond refinement loop for a synthetic Python target."""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


FORMAT = "ds4-diamond-refinement-run-v1"
SYNTHETIC_MODULE = "coal_example"
SYNTHETIC_SOURCE = """def _plus_one(value):
    return value + 1

def answer(value):
    return _plus_one(value)
"""


@dataclass(frozen=True)
class _Audit:
    loc: int
    function_count: int
    single_caller_helpers: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "loc": self.loc,
            "function_count": self.function_count,
            "single_caller_helper_count": len(self.single_caller_helpers),
            "single_caller_helpers": self.single_caller_helpers,
        }


class _DiamondProposalClient(Protocol):
    provider_id: str

    def propose_refactor(self, source: str, candidate_kind: str) -> dict[str, Any]:
        ...


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _logic_loc(text: str) -> int:
    return sum(
        1 for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _audit_source(text: str) -> _Audit:
    tree = ast.parse(text)
    defs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    names = {node.name for node in defs if node.name.startswith("_")}
    calls = {name: 0 for name in names}
    for node in ast.walk(tree):
        if _is_tracked_call(node, calls):
            calls[node.func.id] += 1
    helpers = sorted(name for name, count in calls.items() if count == 1)
    return _Audit(_logic_loc(text), len(defs), helpers)


def _safe_audit_source(text: str) -> _Audit:
    try:
        return _audit_source(text)
    except SyntaxError:
        return _Audit(_logic_loc(text), 0, [])


def _is_tracked_call(node: ast.AST, calls: dict[str, int]) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in calls
    )


def _validate_python_source(text: str) -> dict[str, Any]:
    try:
        ast.parse(text)
    except SyntaxError as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "error": ""}


def _run_check(root: Path) -> dict[str, Any]:
    cmd = [sys.executable, "-c", f"import {SYNTHETIC_MODULE} as c; print(c.answer(41))"]
    result = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True, timeout=10)
    return {
        "command": " ".join(cmd),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _score(before: _Audit, after: _Audit) -> int:
    loc_delta = before.loc - after.loc
    helper_delta = len(before.single_caller_helpers) - len(after.single_caller_helpers)
    return loc_delta + (3 * helper_delta)


def _node(name: str, tier: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"node": name, "tier": tier, "status": status, **extra}


def _prepare_sandbox(root: Path) -> tuple[Path, Path, Path]:
    before_dir = root / "before"
    after_dir = root / "after"
    before_dir.mkdir()
    after_dir.mkdir()
    before_path = before_dir / f"{SYNTHETIC_MODULE}.py"
    before_path.write_text(SYNTHETIC_SOURCE, encoding="utf-8")
    shutil.copy2(before_path, after_dir / before_path.name)
    return before_dir, after_dir, before_path


def _proposal_nodes(before_audit: _Audit, candidate: str | None, proposal: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _node("parse_targets", "deterministic", "passed", function_count=before_audit.function_count),
        _node("identify_inline_candidates", "deterministic", "passed", candidates=before_audit.single_caller_helpers),
        _node("propose_inline_refactor", "local_small", "passed" if candidate else "no_op", **proposal),
    ]


def _verifier_nodes(root: Path, behavior_same: bool, delta: int) -> list[dict[str, Any]]:
    return [
        _node("apply_to_sandbox", "deterministic", "passed", sandbox_root=str(root)),
        _node("run_tests", "deterministic", "passed" if behavior_same else "failed", byte_identical_output=behavior_same),
        _node("run_audit", "deterministic", "passed", diamond_delta=delta),
        _node("score_candidate", "deterministic", "accepted" if behavior_same and delta > 0 else "rejected"),
    ]


def _record(
    before_path: Path,
    before_audit: _Audit,
    after_text: str,
    after_audit: _Audit,
    behavior: dict[str, Any],
    delta: int,
    nodes: list[dict[str, Any]],
    proposal: dict[str, Any],
) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "domain": "python_diamond_refinement",
        "phase": "A_synthetic_inline_path",
        "status": "passed" if behavior["byte_identical_output"] and delta > 0 else "failed",
        "frontier_call_count": 0,
        "local_model_call_count": 1,
        "sandbox_isolation": True,
        "source": {
            "path": str(before_path),
            "sha256": _sha256_text(SYNTHETIC_SOURCE),
            "audit": before_audit.as_dict(),
        },
        "candidate": {
            "sha256": _sha256_text(after_text),
            "audit": after_audit.as_dict(),
            "diff": _diff(SYNTHETIC_SOURCE, after_text),
            "syntax": _validate_python_source(after_text),
        },
        "proposal": proposal,
        "behavior": behavior,
        "diamond_delta": delta,
        "nodes": nodes,
    }


def _diff(before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="before/coal_example.py",
            tofile="after/coal_example.py",
        )
    )


def _model_proposal(model_client: _DiamondProposalClient, source: str) -> tuple[str | None, dict[str, Any]]:
    response = model_client.propose_refactor(source, "single_caller_inline")
    candidate = response.get("candidate_source")
    if not isinstance(candidate, str) or not candidate.strip():
        return None, {"reason": "local_model_returned_empty_candidate", "provider_id": model_client.provider_id}
    proposal = {
        "provider_id": response.get("provider_id") or model_client.provider_id,
        "api_style": response.get("api_style") or "unknown",
        "candidate_kind": response.get("candidate_kind") or "single_caller_inline",
        "candidate_sha256": _sha256_text(candidate),
    }
    if "generated_token_count" in response:
        proposal["generated_token_count"] = response["generated_token_count"]
    if "elapsed_seconds" in response:
        proposal["model_elapsed_seconds"] = response["elapsed_seconds"]
    return candidate, proposal


def run_synthetic(model_client: _DiamondProposalClient, output: Path | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds4-diamond-refine-") as temp:
        root = Path(temp)
        before_dir, after_dir, before_path = _prepare_sandbox(root)
        before_audit = _audit_source(SYNTHETIC_SOURCE)
        candidate, proposal = _model_proposal(model_client, SYNTHETIC_SOURCE)
        if candidate is not None:
            (after_dir / before_path.name).write_text(candidate, encoding="utf-8")
        after_text = (after_dir / before_path.name).read_text(encoding="utf-8")
        before_check = _run_check(before_dir)
        after_check = _run_check(after_dir)
        after_audit = _safe_audit_source(after_text)
        behavior_same = before_check == after_check and before_check["returncode"] == 0
        delta = _score(before_audit, after_audit)
        nodes = _proposal_nodes(before_audit, candidate, proposal)
        nodes.extend(_verifier_nodes(root, behavior_same, delta))
        behavior = {"before": before_check, "after": after_check, "byte_identical_output": behavior_same}
        record = _record(before_path, before_audit, after_text, after_audit, behavior, delta, nodes, proposal)
    if output is not None:
        record["artifact_path"] = str(output)
        _write_json(output, record)
    return record
