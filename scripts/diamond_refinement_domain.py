#!/usr/bin/env python3
"""Phase-A diamond refinement loop for a synthetic Python target."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FORMAT = "ds4-diamond-refinement-run-v1"
SYNTHETIC_MODULE = "coal_example"
SYNTHETIC_SOURCE = """def _plus_one(value):
    return value + 1

def answer(value):
    return _plus_one(value)
"""


@dataclass(frozen=True)
class Audit:
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


class _NameReplace(ast.NodeTransformer):
    def __init__(self, old: str, new: ast.AST):
        self.old = old
        self.new = new

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id == self.old and isinstance(node.ctx, ast.Load):
            return ast.copy_location(copy.deepcopy(self.new), node)
        return node


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _logic_loc(text: str) -> int:
    return sum(
        1 for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def audit_source(text: str) -> Audit:
    tree = ast.parse(text)
    defs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    names = {node.name for node in defs if node.name.startswith("_")}
    calls = {name: 0 for name in names}
    for node in ast.walk(tree):
        if _is_tracked_call(node, calls):
            calls[node.func.id] += 1
    helpers = sorted(name for name, count in calls.items() if count == 1)
    return Audit(_logic_loc(text), len(defs), helpers)


def _is_tracked_call(node: ast.AST, calls: dict[str, int]) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in calls
    )


def _single_return(node: ast.FunctionDef) -> ast.Return | None:
    if len(node.body) != 1 or not isinstance(node.body[0], ast.Return):
        return None
    return node.body[0]


def _inline_metadata(helper_name: str, node: ast.FunctionDef, ret: ast.Return) -> dict[str, Any] | None:
    if not isinstance(ret.value, ast.Call):
        return None
    call = ret.value
    if not isinstance(call.func, ast.Name):
        return None
    if call.func.id != helper_name or len(call.args) != 1 or call.keywords:
        return None
    return {"caller": node.name, "call_arg": call.args[0]}


def _replace_one_arg(expr: ast.AST, old: str, new: ast.AST) -> ast.AST:
    replaced = _NameReplace(old, new).visit(ast.fix_missing_locations(expr))
    return ast.fix_missing_locations(replaced)


def propose_inline_refactor(text: str) -> tuple[str | None, dict[str, Any]]:
    tree = ast.parse(text)
    defs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for helper_name in audit_source(text).single_caller_helpers:
        helper = defs.get(helper_name)
        if helper is None or len(helper.args.args) != 1 or len(helper.body) != 1:
            continue
        helper_return = _single_return(helper)
        if helper_return is None or helper_return.value is None:
            continue
        arg_name = helper.args.args[0].arg
        for node in list(tree.body):
            if not isinstance(node, ast.FunctionDef) or node.name == helper_name or len(node.body) != 1:
                continue
            ret = _single_return(node)
            if ret is None:
                continue
            metadata = _inline_metadata(helper_name, node, ret)
            if metadata is None:
                continue
            ret.value = _replace_one_arg(helper_return.value, arg_name, metadata["call_arg"])
            tree.body = [item for item in tree.body if item is not helper]
            ast.fix_missing_locations(tree)
            return ast.unparse(tree) + "\n", {
                "inlined_helper": helper_name,
                "caller": metadata["caller"],
            }
    return None, {"reason": "no_single_caller_inline_candidate"}


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


def _score(before: Audit, after: Audit) -> int:
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


def _proposal_nodes(before_audit: Audit, candidate: str | None, proposal: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _node("parse_targets", "deterministic", "passed", function_count=before_audit.function_count),
        _node("identify_inline_candidates", "deterministic", "passed", candidates=before_audit.single_caller_helpers),
        _node("propose_inline_refactor", "deterministic_template", "passed" if candidate else "no_op", **proposal),
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
    before_audit: Audit,
    after_text: str,
    after_audit: Audit,
    behavior: dict[str, Any],
    delta: int,
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "domain": "python_diamond_refinement",
        "phase": "A_synthetic_inline_path",
        "status": "passed" if behavior["byte_identical_output"] and delta > 0 else "failed",
        "frontier_call_count": 0,
        "local_model_call_count": 0,
        "sandbox_isolation": True,
        "source": {
            "path": str(before_path),
            "sha256": sha256_text(SYNTHETIC_SOURCE),
            "audit": before_audit.as_dict(),
        },
        "candidate": {"sha256": sha256_text(after_text), "audit": after_audit.as_dict()},
        "behavior": behavior,
        "diamond_delta": delta,
        "nodes": nodes,
    }


def run_synthetic(output: Path | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds4-diamond-refine-") as temp:
        root = Path(temp)
        before_dir, after_dir, before_path = _prepare_sandbox(root)
        before_audit = audit_source(SYNTHETIC_SOURCE)
        candidate, proposal = propose_inline_refactor(SYNTHETIC_SOURCE)
        if candidate is not None:
            (after_dir / before_path.name).write_text(candidate, encoding="utf-8")
        after_text = (after_dir / before_path.name).read_text(encoding="utf-8")
        before_check = _run_check(before_dir)
        after_check = _run_check(after_dir)
        after_audit = audit_source(after_text)
        behavior_same = before_check == after_check and before_check["returncode"] == 0
        delta = _score(before_audit, after_audit)
        nodes = _proposal_nodes(before_audit, candidate, proposal)
        nodes.extend(_verifier_nodes(root, behavior_same, delta))
        behavior = {"before": before_check, "after": after_check, "byte_identical_output": behavior_same}
        record = _record(before_path, before_audit, after_text, after_audit, behavior, delta, nodes)
    if output is not None:
        record["artifact_path"] = str(output)
        _write_json(output, record)
    return record
