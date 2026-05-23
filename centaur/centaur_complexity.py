#!/usr/bin/env python3
from __future__ import annotations

import ast
import fnmatch
import gzip
import hashlib
import json
import keyword
import math
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional


class ComplexityError(Exception):
    pass


_EVOLUTION_SCORE_FORMAT = "centaur-evolution-score-v1"
_COMPLEXITY_PROFILE_FORMAT = "centaur-complexity-profile-v1"
_COMPLEXITY_SCAN_FORMAT = "centaur-complexity-scan-v1"
_COMPLEXITY_TREND_FORMAT = "centaur-complexity-trend-v1"
_COMPLEXITY_DRILLDOWN_FORMAT = "centaur-complexity-drilldown-v1"
_COMPLEXITY_CALIBRATION_FORMAT = "centaur-complexity-calibration-v1"
_COMPLEXITY_GATE_FORMAT = "centaur-complexity-gate-v1"
_COMPLEXITY_MODULE_PLAN_FORMAT = "centaur-complexity-module-plan-v1"
_PRODUCT_SCOPE_FORMAT = "centaur-product-scope-v1"
_DEFAULT_COMPLEXITY_PROFILE_ID = "locality_modularity_state_dry_v5"
_DEFAULT_COMPLEXITY_GATE_MAX_SCORE_INCREASE = 0.0
_DEFAULT_COMPLEXITY_GATE_MAX_MAX_FUNCTION_LINES_INCREASE = 0
_DEFAULT_COMPLEXITY_GATE_MAX_FUNCTIONS_OVER_50_INCREASE = 0
_DEFAULT_COMPLEXITY_GATE_MAX_FUNCTIONS_OVER_100_INCREASE = 0
_DEFAULT_COMPLEXITY_GATE_MAX_REPEATED_BLOCKS_INCREASE = 0
_DEFAULT_COMPLEXITY_GATE_MAX_FILE_LINES_INCREASE = 0
_DEFAULT_COMPLEXITY_GATE_MAX_FILE_FUNCTIONS_INCREASE = 0
_DEFAULT_INPUT_COMPLEXITY_ALPHA = 1.0
_DEFAULT_INPUT_COMPLEXITY_BETA = 128.0
_DEFAULT_INPUT_COMPLEXITY_GAMMA = 64.0
_TEXT_EXTENSIONS = {
    ".c", ".h", ".sh", ".bash", ".py", ".proc", ".llm", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".md", ".markdown", ".gitignore", ".gitattributes"
}
_C_EXTENSIONS = {".c", ".h"}
_BASH_EXTENSIONS = {".sh", ".bash"}
_PYTHON_EXTENSIONS = {".py"}
_IGNORED_TRANSFORM_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".centaur", "agent-clones"}
_PRODUCT_SCOPE_ARTIFACT_DIRS = {"venv", ".venv", "dist", "build", ".centaur", ".tox", ".mypy_cache", ".pytest_cache", "__pycache__", "node_modules"}
_PRODUCT_SCOPE_MODES = {"all", "all_files", "git_tracked", "ignore_aware", "explicit_include_exclude"}


_COMPLEXITY_PUBLIC_API_NAMES = (
    "ComplexityError",
    "build_complexity_profile",
    "source_complexity_summary",
    "scan_complexity",
    "scan_complexity_or_missing",
    "append_complexity_trend_record",
    "summarize_complexity_trend",
    "evaluate_complexity_gate",
    "complexity_drilldown",
    "build_complexity_module_plan",
    "calibrate_complexity_metric",
    "compact_complexity_scan",
    "canonicalize_text_for_complexity",
    "select_product_scope_files",
)

__all__ = _COMPLEXITY_PUBLIC_API_NAMES


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _looks_like_text_file(path: Path) -> bool:
    if path.suffix.lower() in _TEXT_EXTENSIONS:
        return True
    try:
        data = path.read_bytes()[:8192]
    except OSError:
        return False
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _read_ndjson_records_with_format(path: Path, expected_format: str, label: str, limit: int = 0) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if limit > 0:
        lines = lines[-limit:]
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ComplexityError(f"invalid {label} JSON at {path}:{line_number}: {exc}") from exc
        if not isinstance(record, dict) or record.get("format") != expected_format:
            raise ComplexityError(f"invalid {label} format at {path}:{line_number}")
        records.append(record)
    return records


def _append_ndjson_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _hyor_now_us() -> int:
    return int(time.time() * 1000000)


def _squash_whitespace(value: str) -> str:
    return " ".join(value.split())


def _ascii_word_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for char in text:
        if char.isascii() and (char.isalnum() or char == "_"):
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def _ascii_identifier_tokens(text: str) -> list[str]:
    return [token for token in _ascii_word_tokens(text) if token and (token[0].isalpha() or token[0] == "_")]


def _is_ascii_identifier(text: str) -> bool:
    tokens = _ascii_identifier_tokens(text)
    return len(tokens) == 1 and tokens[0] == text


def _split_on_blank_lines(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _split_identifier_words(identifier: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    for index, char in enumerate(identifier):
        if char.isascii() and char.isalnum():
            next_char = identifier[index + 1] if index + 1 < len(identifier) else ""
            if current and char.isupper() and (current[-1].islower() or current[-1].isdigit() or (current[-1].isupper() and next_char.islower())):
                words.append("".join(current).lower())
                current = [char]
            else:
                current.append(char)
        elif current:
            words.append("".join(current).lower())
            current = []
    if current:
        words.append("".join(current).lower())
    return [word for word in words if word]


def _sanitize_module_name_piece(value: str) -> str:
    chars: list[str] = []
    previous_underscore = False
    for char in value.lower():
        if char.isascii() and (char.isalnum() or char == "_"):
            chars.append(char)
            previous_underscore = False
        elif not previous_underscore:
            chars.append("_")
            previous_underscore = True
    return "".join(chars).strip("_") or "module"


def canonicalize_text_for_complexity(text: str) -> str:
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        lines.append(line.rstrip())
    return "\n".join(lines).strip() + "\n"

def _git_tracked_relative_paths(root: Path) -> set[str]:
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise ComplexityError("git_tracked product scope requires a git worktree")
    entries = result.stdout.decode("utf-8", errors="replace").split("\0")
    return {entry for entry in entries if entry}


def _git_ignored_relative_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--directory"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ComplexityError("ignore_aware product scope requires a git worktree")
    entries = result.stdout.decode("utf-8", errors="replace").split("\0")
    return {entry for entry in entries if entry}


def _matches_product_pattern(relative_path: str, pattern: str) -> bool:
    normalized = pattern.strip().strip("/")
    if not normalized:
        return False
    if pattern.endswith("/"):
        return relative_path == normalized or relative_path.startswith(normalized + "/")
    return fnmatch.fnmatch(relative_path, normalized) or fnmatch.fnmatch(Path(relative_path).name, normalized)


def _git_ignored_path_match(relative_path: str, ignored_paths: set[str]) -> bool:
    if relative_path in ignored_paths:
        return True
    return any(item.endswith("/") and relative_path.startswith(item) for item in ignored_paths)


def _product_scope_exclusion_reason(relative_path: str, product_scope: str, ignored_paths: set[str], exclude_patterns: list[str]) -> str | None:
    parts = relative_path.split("/")
    if product_scope == "all_files":
        return None
    if product_scope in {"all", "git_tracked", "ignore_aware", "explicit_include_exclude"}:
        for part in parts:
            if part in _PRODUCT_SCOPE_ARTIFACT_DIRS:
                return f"artifact_dir:{part}"
    if product_scope == "ignore_aware":
        if _git_ignored_path_match(relative_path, ignored_paths):
            return "git_ignored"
    for pattern in exclude_patterns:
        if _matches_product_pattern(relative_path, pattern):
            return f"exclude_pattern:{pattern}"
    return None


def _include_product_scope_path(relative_path: str, include_patterns: list[str]) -> bool:
    if not include_patterns:
        return True
    return any(_matches_product_pattern(relative_path, pattern) for pattern in include_patterns)


def select_product_scope_files(
    path: Path,
    product_scope: str = "all",
    include_patterns: Optional[list[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
    text_only: bool = True,
    python_only: bool = False,
) -> dict[str, Any]:
    if product_scope not in _PRODUCT_SCOPE_MODES:
        raise ComplexityError(f"unsupported product scope: {product_scope}")
    path = path.resolve()
    root = path if path.is_dir() else path.parent
    selected: list[Path] = []
    excluded: list[dict[str, str]] = []
    include_list = include_patterns or []
    exclude_list = exclude_patterns or []
    tracked_paths = _git_tracked_relative_paths(root) if product_scope == "git_tracked" else None
    ignored_paths = _git_ignored_relative_paths(root) if product_scope == "ignore_aware" else set()

    def add_excluded(relative_path: str, reason: str) -> None:
        excluded.append({"path": relative_path, "reason": reason})

    def should_prune_dir(relative_path: str, name: str) -> str | None:
        if name in {".git", ".hg", ".svn"}:
            return "vcs_dir"
        if product_scope == "all":
            product_reason = _product_scope_exclusion_reason(relative_path, product_scope, ignored_paths, exclude_list)
            if product_reason is not None:
                return product_reason
            if name in _IGNORED_TRANSFORM_DIRS or name.startswith("."):
                return f"legacy_ignored_dir:{name}"
            return None
        if product_scope == "all_files":
            return None
        return _product_scope_exclusion_reason(relative_path, product_scope, ignored_paths, exclude_list)

    if path.is_file():
        candidates = [path]
    elif path.is_dir():
        candidates = []
        for current, dirnames, filenames in os.walk(path):
            current_path = Path(current)
            kept_dirs: list[str] = []
            for name in sorted(dirnames):
                dir_path = current_path / name
                relative_dir = dir_path.relative_to(root).as_posix() if _path_inside(dir_path, root) else name
                reason = should_prune_dir(relative_dir, name)
                if reason is None:
                    kept_dirs.append(name)
                else:
                    add_excluded(relative_dir + "/", reason)
            dirnames[:] = kept_dirs
            for filename in filenames:
                if product_scope == "all" and filename.startswith(".") and filename not in {".gitignore", ".gitattributes"}:
                    continue
                item = current_path / filename
                if item.is_file() and not item.is_symlink():
                    candidates.append(item)
    else:
        raise ComplexityError(f"complexity path does not exist: {path}")
    for item in sorted(candidates):
        if text_only and not _looks_like_text_file(item):
            continue
        if python_only and item.suffix != ".py":
            continue
        relative = item.relative_to(root).as_posix() if _path_inside(item, root) else item.name
        reason = None
        if tracked_paths is not None and relative not in tracked_paths:
            reason = "not_git_tracked"
        if reason is None and not _include_product_scope_path(relative, include_list):
            reason = "not_explicitly_included"
        if reason is None:
            reason = _product_scope_exclusion_reason(relative, product_scope, ignored_paths, exclude_list)
        if reason is None:
            selected.append(item)
        else:
            excluded.append({"path": relative, "reason": reason})
    return {
        "format": _PRODUCT_SCOPE_FORMAT,
        "mode": product_scope,
        "root": str(root),
        "selected_paths": [str(item) for item in selected],
        "selected_relative_paths": [item.relative_to(root).as_posix() if _path_inside(item, root) else item.name for item in selected],
        "selected_file_count": len(selected),
        "excluded_paths": excluded[:250],
        "excluded_path_count": len(excluded),
        "excluded_paths_truncated": len(excluded) > 250,
        "artifact_dir_exclusions": {
            name: any(str(record.get("reason", "")).startswith(f"artifact_dir:{name}") for record in excluded)
            for name in ("venv", ".venv", "dist", "build", "node_modules")
        },
        "include_patterns": include_list,
        "exclude_patterns": exclude_list,
        "ignored_path_count": len(ignored_paths),
    }


def _complexity_source_file_paths(path: Path, product_scope: str = "all", include_patterns: Optional[list[str]] = None, exclude_patterns: Optional[list[str]] = None) -> list[Path]:
    selection = select_product_scope_files(path, product_scope, include_patterns, exclude_patterns, text_only=True)
    return [Path(item) for item in selection["selected_paths"]]


def _count_generic_decision_points(text: str) -> int:
    decision_words = {"if", "elif", "for", "while", "case", "catch", "except", "with", "assert"}
    keyword_count = sum(1 for token in _ascii_word_tokens(text) if token in decision_words)
    return keyword_count + text.count("&&") + text.count("||") + text.count("?")


def _python_source_complexity(text: str) -> tuple[int, int]:
    try:
        module = ast.parse(text)
    except SyntaxError:
        return max(1, _count_generic_decision_points(text)), max((len(block) for block in _split_on_blank_lines(text)), default=0)
    total = 0
    max_loc = 0
    decision_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Match)
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start)
            loc = max(1, int(end) - int(start) + 1)
            max_loc = max(max_loc, loc)
            decisions = 0
            for child in ast.walk(node):
                if isinstance(child, decision_nodes):
                    decisions += 1
                elif isinstance(child, ast.BoolOp):
                    decisions += max(1, len(getattr(child, "values", [])) - 1)
            total += 1 + decisions
    if total == 0:
        total = _count_generic_decision_points(text)
    return total, max_loc


def _c_like_function_header(header: str) -> bool:
    candidate = _squash_whitespace(header.strip())
    if not candidate or ";" in candidate:
        return False
    open_paren = candidate.rfind("(")
    close_paren = candidate.rfind(")")
    if open_paren <= 0 or close_paren != len(candidate) - 1:
        return False
    before_paren = candidate[:open_paren].strip()
    function_name = before_paren.replace("*", " ").split()[-1] if before_paren.replace("*", " ").split() else ""
    if not _is_ascii_identifier(function_name):
        return False
    first = candidate.split(None, 1)[0]
    if first in {"if", "for", "while", "switch", "case", "do", "else", "struct", "union", "enum", "typedef", "return"}:
        return False
    return True


def _c_like_source_complexity(text: str) -> tuple[int, int]:
    lines = text.splitlines()
    total = 0
    max_loc = 0
    in_function = False
    brace_depth = 0
    start_index = 0
    collected: list[str] = []
    header_window: list[str] = []
    for index, line in enumerate(lines):
        if not in_function:
            header_window.append(line)
            if len(header_window) > 8:
                header_window.pop(0)
            if "{" not in line:
                continue
            before_brace = "\n".join(header_window).split("{", 1)[0]
            if not _c_like_function_header(before_brace):
                header_window = [] if "}" in line else header_window
                continue
            in_function = True
            start_index = index
            collected = [line]
            brace_depth = line.count("{") - line.count("}")
            if brace_depth <= 0:
                body = "\n".join(collected)
                total += 1 + _count_generic_decision_points(body)
                max_loc = max(max_loc, index - start_index + 1)
                in_function = False
                collected = []
                header_window = []
        else:
            collected.append(line)
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                body = "\n".join(collected)
                total += 1 + _count_generic_decision_points(body)
                max_loc = max(max_loc, index - start_index + 1)
                in_function = False
                collected = []
                header_window = []
    if total == 0:
        total = _count_generic_decision_points(text)
    return total, max_loc


def _shell_source_complexity(text: str) -> tuple[int, int]:
    shell_words = {"then", "elif", "case", "function"}
    total = _count_generic_decision_points(text) + sum(1 for token in _ascii_word_tokens(text) if token in shell_words)
    max_loc = 0
    current = 0
    for line in text.splitlines():
        if line.strip():
            current += 1
            max_loc = max(max_loc, current)
        else:
            current = 0
    return max(1, total), max_loc


def _source_file_complexity(path: Path, root: Path) -> dict[str, Any]:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    canonical = canonicalize_text_for_complexity(text)
    suffix = path.suffix.lower()
    if suffix == ".py":
        cyclomatic_sum, max_function_loc = _python_source_complexity(text)
    elif suffix in _C_EXTENSIONS:
        cyclomatic_sum, max_function_loc = _c_like_source_complexity(text)
    elif suffix in _BASH_EXTENSIONS:
        cyclomatic_sum, max_function_loc = _shell_source_complexity(text)
    else:
        cyclomatic_sum, max_function_loc = _count_generic_decision_points(text), 0
    return {"path": str(path), "relative_path": path.relative_to(root).as_posix() if _path_inside(path, root) else path.name, "raw_size_bytes": len(data), "canonical_size_bytes": len(canonical.encode("utf-8")), "canonical_sha256": _sha256_bytes(canonical.encode("utf-8")), "cyclomatic_sum": int(cyclomatic_sum), "max_function_loc": int(max_function_loc)}


def source_complexity_summary(path: Path, alpha: float = _DEFAULT_INPUT_COMPLEXITY_ALPHA, beta: float = _DEFAULT_INPUT_COMPLEXITY_BETA, gamma: float = _DEFAULT_INPUT_COMPLEXITY_GAMMA, include_files: bool = False) -> dict[str, Any]:
    resolved = path.resolve()
    files = _complexity_source_file_paths(resolved)
    canonical_parts: list[str] = []
    records: list[dict[str, Any]] = []
    for item in files:
        record = _source_file_complexity(item, resolved if resolved.is_dir() else item.parent)
        canonical = canonicalize_text_for_complexity(item.read_text(encoding="utf-8", errors="replace"))
        canonical_parts.append(f"--- {record['relative_path']}\n{canonical}")
        records.append(record)
    canonical_blob = "".join(canonical_parts).encode("utf-8")
    gzip_size = len(gzip.compress(canonical_blob, compresslevel=9)) if canonical_blob else 0
    cyclomatic_sum = sum(int(item["cyclomatic_sum"]) for item in records)
    max_function_loc = max((int(item["max_function_loc"]) for item in records), default=0)
    input_complexity = float(alpha) * gzip_size + float(beta) * cyclomatic_sum + float(gamma) * max_function_loc
    result: dict[str, Any] = {"format": _EVOLUTION_SCORE_FORMAT, "status": "success", "path": str(resolved), "file_count": len(records), "raw_size_bytes": sum(int(item["raw_size_bytes"]) for item in records), "canonical_size_bytes": len(canonical_blob), "gzip_canonical_size_bytes": gzip_size, "canonical_sha256": _sha256_bytes(canonical_blob), "cyclomatic_sum": cyclomatic_sum, "max_function_loc": max_function_loc, "input_complexity": input_complexity, "weights": {"alpha": float(alpha), "beta": float(beta), "gamma": float(gamma)}}
    if include_files:
        result["files"] = records
    return result


_COMPLEXITY_COMPONENT_NAMES = (
    "compressed_load",
    "branching",
    "function_size",
    "function_state",
    "nesting",
    "duplication",
    "naming_noise",
    "line_shape",
    "file_architecture",
    "module_interface",
    "module_boundary",
    "comment_balance",
)

_COMPLEXITY_ALLOWED_SHORT_IDENTIFIERS = {
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "m", "n", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "ch", "db", "fd", "fp", "fs", "id", "io", "ip", "js", "ok", "os", "pc", "py", "rc", "re", "rv", "sh", "ui", "us", "vm",
}

_COMPLEXITY_VAGUE_IDENTIFIERS = {
    "arg", "args", "bar", "baz", "blob", "data", "datum", "foo", "helper", "helpers", "info", "item", "items", "manager", "misc",
    "object", "obj", "payload", "processor", "stuff", "temp", "tmp", "util", "utils", "value", "values", "var", "vars",
}

_COMPLEXITY_GENERIC_NAME_TERMS = {
    "add", "append", "apply", "build", "calculate", "check", "collect", "command", "compact", "create", "default", "emit", "ensure",
    "evaluate", "execute", "expand", "find", "get", "handle", "index", "latest", "list", "load", "make", "normalize", "parse", "print",
    "read", "record", "render", "resolve", "run", "save", "scan", "select", "set", "summarize", "sync", "update", "validate", "write",
}

_COMPLEXITY_BROAD_MODULE_TERMS = {
    "adapter", "artifact", "benchmark", "complexity", "config", "context", "decomposition", "dry", "episode", "evolution", "piece",
    "procedure", "project", "release", "repair", "sandbox", "shorthand", "source", "state", "test", "tool", "training", "transform",
}

_COMPLEXITY_HYOR_SUBDOMAIN_TERMS = {
    "admission", "agent", "api", "compact", "config", "controller", "dashboard", "distribution", "executor", "http", "model", "node",
    "provider", "ring", "route", "runtime", "spark", "supervisor", "telemetry", "topology",
}

_COMPLEXITY_EXTERNAL_ENTRYPOINT_PREFIXES = (
    "command_",
    "execute_hyor_controller_",
    "main",
)

_COMPLEXITY_FILESYSTEM_EFFECT_MARKERS = {
    "open", "path.read_text", "path.write_text", "path.read_bytes", "path.write_bytes", "shutil.copy", "shutil.copy2",
    "shutil.copytree", "shutil.move", "shutil.rmtree", "os.remove", "os.unlink", "os.rename", "os.replace", "os.makedirs",
    "path.mkdir", "path.unlink", "path.rename", "path.replace", "json.dump", "tarfile.open", "zipfile.zipfile",
}

_COMPLEXITY_PROCESS_EFFECT_MARKERS = {
    "subprocess.run", "subprocess.popen", "os.system", "os.kill", "os.fork", "signal.signal", "signal.alarm",
}

_COMPLEXITY_NETWORK_EFFECT_MARKERS = {
    "socket.socket", "socket.create_connection", "urllib.request.urlopen", "http.server.httpserver", "requests.get",
    "requests.post", "requests.request",
}

_COMPLEXITY_NONDETERMINISTIC_EFFECT_MARKERS = {
    "time.time", "time.sleep", "uuid.uuid4", "random.random", "random.randrange", "random.randint",
}

_COMPLEXITY_CONCURRENCY_EFFECT_MARKERS = {
    "threading.thread", "threadpoolexecutor", "processpoolexecutor", "multiprocessing.process", "asyncio.create_task",
    "asyncio.gather", "socketserver.threadingmixin", "concurrent.futures",
}

_COMPLEXITY_CODE_SUFFIXES = _PYTHON_EXTENSIONS | _C_EXTENSIONS | _BASH_EXTENSIONS


def build_complexity_profile() -> dict[str, Any]:
    return {
        "format": _COMPLEXITY_PROFILE_FORMAT,
        "status": "success",
        "version": 1,
        "profile_id": _DEFAULT_COMPLEXITY_PROFILE_ID,
        "direction": "lower_is_better",
        "score_formula": "compressed_load + branching + function_size + function_state + nesting + duplication + naming_noise + line_shape + file_architecture + module_interface + module_boundary + comment_balance",
        "components": {
            "compressed_load": {"description": "gzip(canonical_source).bytes / 1024"},
            "branching": {"description": "2 * cyclomatic_sum + 4 * max(0, max_function_cyclomatic - 10)"},
            "function_size": {"description": "quadratic penalties after 50 and 100 function lines, plus counts of functions over the 50-line suspicious threshold"},
            "function_state": {"description": "function-level state pressure from parameter count, local bindings, exits, global writes, direct side-effect domains, and concurrency touchpoints"},
            "nesting": {"description": "penalty after nesting depth 4"},
            "duplication": {"description": "repeated normalized 5-line block count plus repeated normalized block byte estimate"},
            "naming_noise": {"description": "short identifiers outside allowed loop/system names plus vague identifiers"},
            "line_shape": {"description": "lines over 100 chars plus stronger penalty for lines over 140 chars"},
            "file_architecture": {"description": "godfile pressure from very large files, excessive per-file function counts, and too many top-level definitions"},
            "module_interface": {"description": "declared module API width, leaked non-API top-level functions/classes/values, missing declared API names, mutable global state, import-time effects, side-effect surface, and public concurrency leakage"},
            "module_boundary": {"description": "missed modular seams inferred from cohesive function clusters with small preserved APIs"},
            "comment_balance": {"description": "small sparse/heavy comment-ratio penalty for larger source files"},
        },
        "thresholds": {
            "suspicious_function_lines": 50,
            "strongly_suspicious_function_lines": 100,
            "nesting_depth_free_limit": 4,
            "line_length_suspicious": 100,
            "line_length_strong": 140,
            "duplication_block_lines": 5,
            "godfile_lines_suspicious": 1000,
            "godfile_lines_strong": 3000,
            "godfile_lines_severe": 10000,
            "functions_per_file_suspicious": 80,
            "functions_per_file_strong": 250,
            "function_parameters_suspicious": 5,
            "function_locals_suspicious": 12,
            "module_api_items_suspicious": 12,
            "leaked_non_api_names_suspicious": 20,
            "api_boundary_violations_allowed": 0,
            "public_concurrency_api_free_limit": 2,
            "module_candidate_min_functions": 6,
            "module_candidate_good_api_ratio": 0.70,
            "wide_signature_parameters": 4,
            "many_local_names": 12,
        },
        "style_rule": "Compactness is rewarded when it comes from cohesive modules with small APIs, isolated side effects, contained concurrency, clearer structure, smaller functions, lower branching, lower duplication, and clearer names rather than terse shorthand.",
    }


def _complexity_python_function_cyclomatic(node: ast.AST) -> int:
    decision_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Match)
    cyclomatic = 1
    for child in ast.walk(node):
        if isinstance(child, decision_nodes):
            cyclomatic += 1
        elif isinstance(child, ast.BoolOp):
            cyclomatic += max(1, len(getattr(child, "values", [])) - 1)
    return cyclomatic


def _complexity_python_max_nesting_depth(node: ast.AST) -> int:
    control_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.ExceptHandler, ast.Match)

    def walk(current: ast.AST, depth: int) -> int:
        next_depth = depth + 1 if isinstance(current, control_nodes) else depth
        best = next_depth
        for child in ast.iter_child_nodes(current):
            best = max(best, walk(child, next_depth))
        return best

    return walk(node, 0)


def _complexity_python_exit_point_count(node: ast.AST) -> int:
    exits = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.Return, ast.Raise, ast.Yield, ast.YieldFrom)):
            exits += 1
    return exits


def _complexity_python_qualified_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _complexity_python_qualified_call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _complexity_python_side_effect_domains(node: ast.AST) -> list[str]:
    domains: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.Global, ast.Nonlocal)):
            domains.add("global_state")
        if isinstance(child, ast.Await):
            domains.add("async_runtime")
        if not isinstance(child, ast.Call):
            continue
        name = _complexity_python_qualified_call_name(child.func).lower()
        if any(token in name for token in ("open", "write", "read_text", "write_text", "unlink", "mkdir", "rename", "replace")):
            domains.add("filesystem")
        if any(token in name for token in ("subprocess", "popen", "system", "exec", "kill", "wait")):
            domains.add("process")
        if any(token in name for token in ("socket", "http", "request", "urlopen", "server")):
            domains.add("network")
        if any(token in name for token in ("time", "sleep", "clock", "now")):
            domains.add("clock")
        if any(token in name for token in ("env", "getenv", "putenv")):
            domains.add("environment")
        if any(token in name for token in ("thread", "lock", "queue", "executor", "asyncio", "multiprocessing")):
            domains.add("concurrency")
    return sorted(domains)


def _complexity_python_concurrency_touchpoint_count(node: ast.AST) -> int:
    count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Await):
            count += 1
        if isinstance(child, ast.Call):
            name = _complexity_python_qualified_call_name(child.func).lower()
            if any(token in name for token in ("thread", "lock", "queue", "executor", "asyncio", "multiprocessing")):
                count += 1
    return count


def _complexity_python_function_parameter_count(node: ast.AST) -> int:
    arguments = getattr(node, "args", None)
    if arguments is None:
        return 0
    count = len(getattr(arguments, "posonlyargs", [])) + len(getattr(arguments, "args", [])) + len(getattr(arguments, "kwonlyargs", []))
    if getattr(arguments, "vararg", None) is not None:
        count += 1
    if getattr(arguments, "kwarg", None) is not None:
        count += 1
    return count


def _complexity_collect_python_target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in target.elts:
            names.update(_complexity_collect_python_target_names(element))
        return names
    return set()


def _complexity_python_function_local_name_count(node: ast.AST) -> int:
    names: set[str] = set()
    parameter_names = {arg.arg for arg in getattr(getattr(node, "args", None), "args", [])}
    for child in ast.walk(node):
        if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = getattr(child, "targets", [getattr(child, "target", None)])
            for target in targets:
                if target is not None:
                    names.update(_complexity_collect_python_target_names(target))
        elif isinstance(child, (ast.For, ast.AsyncFor, ast.With, ast.AsyncWith)):
            target = getattr(child, "target", None)
            names.update(_complexity_collect_python_target_names(target)) if target is not None else None
            for item in getattr(child, "items", []):
                optional_vars = getattr(item, "optional_vars", None)
                if optional_vars is not None:
                    names.update(_complexity_collect_python_target_names(optional_vars))
    return len(names - parameter_names)


def _complexity_python_call_label(call_node: ast.Call) -> str:
    parts: list[str] = []
    current: ast.AST = call_node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    parts.reverse()
    return ".".join(parts).lower()


def _complexity_effect_flags_from_call_labels(labels: list[str]) -> tuple[list[str], list[str]]:
    side_effects: set[str] = set()
    concurrency: set[str] = set()
    for label in labels:
        normalized = label.lower()
        if any(marker in normalized for marker in _COMPLEXITY_FILESYSTEM_EFFECT_MARKERS):
            side_effects.add("filesystem")
        if any(marker in normalized for marker in _COMPLEXITY_PROCESS_EFFECT_MARKERS):
            side_effects.add("process")
        if any(marker in normalized for marker in _COMPLEXITY_NETWORK_EFFECT_MARKERS):
            side_effects.add("network")
        if any(marker in normalized for marker in _COMPLEXITY_NONDETERMINISTIC_EFFECT_MARKERS):
            side_effects.add("nondeterministic_time")
        if any(marker in normalized for marker in _COMPLEXITY_CONCURRENCY_EFFECT_MARKERS):
            concurrency.add("concurrency")
    return sorted(side_effects), sorted(concurrency)


def _complexity_python_function_effect_flags(node: ast.AST) -> tuple[list[str], list[str]]:
    labels = [_complexity_python_call_label(child) for child in ast.walk(node) if isinstance(child, ast.Call)]
    return _complexity_effect_flags_from_call_labels(labels)


def _complexity_python_function_records(text: str) -> list[dict[str, Any]]:
    try:
        module = ast.parse(text)
    except SyntaxError:
        return []
    records: list[dict[str, Any]] = []
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start_line = int(getattr(node, "lineno", 1))
            end_line = int(getattr(node, "end_lineno", start_line))
            side_effect_flags, concurrency_flags = _complexity_python_function_effect_flags(node)
            if isinstance(node, ast.AsyncFunctionDef) or any(isinstance(child, ast.Await) for child in ast.walk(node)):
                concurrency_flags = sorted(set(concurrency_flags) | {"async_runtime"})
            local_name_count = _complexity_python_function_local_name_count(node)
            records.append({
                "name": node.name,
                "line": start_line,
                "end_line": end_line,
                "line_count": max(1, end_line - start_line + 1),
                "cyclomatic": _complexity_python_function_cyclomatic(node),
                "nesting_depth": _complexity_python_max_nesting_depth(node),
                "parameter_count": _complexity_python_function_parameter_count(node),
                "local_name_count": local_name_count,
                "local_variable_count": local_name_count,
                "exit_point_count": _complexity_python_exit_point_count(node),
                "side_effect_flags": side_effect_flags,
                "side_effect_domains": side_effect_flags,
                "concurrency_flags": concurrency_flags,
                "concurrency_touchpoint_count": len(concurrency_flags),
            })
    records.sort(key=lambda item: (int(item["line"]), str(item["name"])))
    return records


def _complexity_brace_nesting_depth(text: str) -> int:
    depth = 0
    best = 0
    for char in text:
        if char == "{":
            depth += 1
            best = max(best, depth)
        elif char == "}":
            depth = max(0, depth - 1)
    return best


def _complexity_c_like_function_records(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    records: list[dict[str, Any]] = []
    in_function = False
    brace_depth = 0
    start_index = 0
    collected: list[str] = []
    header_window: list[str] = []
    for index, line in enumerate(lines):
        if not in_function:
            header_window.append(line)
            if len(header_window) > 8:
                header_window.pop(0)
            if "{" not in line:
                continue
            before_brace = "\n".join(header_window).split("{", 1)[0]
            if not _c_like_function_header(before_brace):
                if "}" in line:
                    header_window = []
                continue
            in_function = True
            start_index = index
            collected = [line]
            brace_depth = line.count("{") - line.count("}")
            if brace_depth <= 0:
                body = "\n".join(collected)
                records.append({"name": "function", "line": start_index + 1, "end_line": index + 1, "line_count": index - start_index + 1, "cyclomatic": 1 + _count_generic_decision_points(body), "nesting_depth": _complexity_brace_nesting_depth(body)})
                in_function = False
                collected = []
                header_window = []
        else:
            collected.append(line)
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                body = "\n".join(collected)
                records.append({"name": "function", "line": start_index + 1, "end_line": index + 1, "line_count": index - start_index + 1, "cyclomatic": 1 + _count_generic_decision_points(body), "nesting_depth": _complexity_brace_nesting_depth(body)})
                in_function = False
                collected = []
                header_window = []
    return records


def _complexity_shell_function_records(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    records: list[dict[str, Any]] = []
    function_start: Optional[int] = None
    function_name = "function"
    depth = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if function_start is None:
            function_candidate = _shell_function_name_from_line(stripped)
            if function_candidate:
                function_start = index
                function_name = function_candidate
                depth = stripped.count("{") - stripped.count("}")
                if depth <= 0:
                    body = line
                    records.append({"name": function_name, "line": index + 1, "end_line": index + 1, "line_count": 1, "cyclomatic": max(1, _count_generic_decision_points(body)), "nesting_depth": 1})
                    function_start = None
            continue
        depth += stripped.count("{") - stripped.count("}")
        if depth <= 0:
            body = "\n".join(lines[function_start:index + 1])
            records.append({"name": function_name, "line": function_start + 1, "end_line": index + 1, "line_count": index - function_start + 1, "cyclomatic": max(1, _count_generic_decision_points(body)), "nesting_depth": max(1, _complexity_brace_nesting_depth(body))})
            function_start = None
            function_name = "function"
    return records


def _shell_function_name_from_line(stripped: str) -> Optional[str]:
    before_brace, separator, _after_brace = stripped.partition("{")
    if not separator:
        return None
    prefix = before_brace.strip()
    if prefix.startswith("function "):
        prefix = prefix[len("function "):].strip()
    if prefix.endswith(")"):
        open_paren = prefix.rfind("(")
        if open_paren >= 0 and not prefix[open_paren + 1:-1].strip():
            prefix = prefix[:open_paren].strip()
    return prefix if _is_ascii_identifier(prefix) else None


def _complexity_function_records_for_source(text: str, suffix: str) -> list[dict[str, Any]]:
    if suffix in _PYTHON_EXTENSIONS:
        return _complexity_python_function_records(text)
    if suffix in _C_EXTENSIONS:
        return _complexity_c_like_function_records(text)
    if suffix in _BASH_EXTENSIONS:
        return _complexity_shell_function_records(text)
    return []


def _complexity_normalize_line_for_duplication(line: str) -> str:
    normalized = line.strip().lower()
    tokens: list[str] = []
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if char in {"'", '"'}:
            quote = char
            index += 1
            while index < len(normalized):
                if normalized[index] == "\\":
                    index += 2
                    continue
                if normalized[index] == quote:
                    index += 1
                    break
                index += 1
            tokens.append("<str>")
            continue
        if char.isdigit():
            index += 1
            while index < len(normalized) and (normalized[index].isdigit() or normalized[index] in ".xabcdef"):
                index += 1
            tokens.append("<num>")
            continue
        tokens.append(char)
        index += 1
    normalized = _squash_whitespace("".join(tokens))
    words = normalized.split()
    if len(words) >= 2 and words[0] in {"def", "class"} and _is_ascii_identifier(words[1].split("(", 1)[0].split(":", 1)[0]):
        words[1] = words[1].replace(words[1].split("(", 1)[0].split(":", 1)[0], "<ident>", 1)
        normalized = " ".join(words)
    open_paren = normalized.find("(")
    if open_paren > 0:
        before = normalized[:open_paren].rstrip()
        parts = before.replace("*", " ").split()
        if len(parts) >= 2 and _is_ascii_identifier(parts[-1]) and parts[0] not in {"if", "for", "while", "switch"}:
            normalized = before[:before.rfind(parts[-1])] + "<ident>" + normalized[open_paren:]
            normalized = _squash_whitespace(normalized)
    return normalized


def _build_complexity_duplication_examples(block_counts: dict[str, dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for digest, entry in block_counts.items():
        count = int(entry.get("count", 0) or 0)
        if count <= 1:
            continue
        block = entry.get("block")
        block_lines = list(block) if isinstance(block, tuple) else []
        examples.append({
            "count": count,
            "extra_count": count - 1,
            "digest": digest[:16],
            "line_count": len(block_lines),
            "normalized_preview": block_lines[:min(3, len(block_lines))],
        })
    examples.sort(key=lambda item: (-int(item.get("extra_count", 0)), str(item.get("digest", ""))))
    return examples[:limit]


def _complexity_count_normalized_blocks(normalized_lines: list[str], block_line_count: int) -> dict[str, dict[str, Any]]:
    block_counts: dict[str, dict[str, Any]] = {}
    if len(normalized_lines) < block_line_count:
        return block_counts
    for index in range(0, len(normalized_lines) - block_line_count + 1):
        block = tuple(normalized_lines[index:index + block_line_count])
        block_text = "\n".join(block)
        digest = _sha256_bytes(block_text.encode("utf-8", errors="replace"))
        entry = block_counts.get(digest)
        if entry is None:
            block_counts[digest] = {"count": 1, "block": block, "byte_length": len(block_text.encode("utf-8", errors="replace"))}
        else:
            entry["count"] = int(entry.get("count", 0) or 0) + 1
    return block_counts


def _complexity_duplication_component(text: str, block_line_count: int = 5) -> dict[str, Any]:
    normalized_lines: list[str] = []
    for line in text.splitlines():
        normalized = _complexity_normalize_line_for_duplication(line)
        if normalized:
            normalized_lines.append(normalized)
    block_counts = _complexity_count_normalized_blocks(normalized_lines, block_line_count)
    repeated_block_count = 0
    repeated_block_byte_estimate = 0
    repeated_group_count = 0
    for entry in block_counts.values():
        count = int(entry.get("count", 0) or 0)
        if count <= 1:
            continue
        repeated_group_count += 1
        repeated_block_count += count - 1
        repeated_block_byte_estimate += (count - 1) * int(entry.get("byte_length", 0) or 0)
    return {
        "repeated_group_count": repeated_group_count,
        "repeated_normalized_blocks": repeated_block_count,
        "repeated_block_byte_estimate": repeated_block_byte_estimate,
        "duplicate_block_examples": _build_complexity_duplication_examples(block_counts),
        "duplication": float(repeated_block_count + repeated_block_byte_estimate),
    }

def _complexity_naming_noise_component(text: str, suffix: str) -> dict[str, Any]:
    if suffix not in _COMPLEXITY_CODE_SUFFIXES:
        return {"short_identifier_count": 0, "vague_identifier_count": 0, "naming_noise": 0.0}
    identifiers = _ascii_identifier_tokens(text)
    short_identifier_count = 0
    vague_identifier_count = 0
    for identifier in identifiers:
        lower = identifier.lower()
        if keyword.iskeyword(lower):
            continue
        if lower in _COMPLEXITY_VAGUE_IDENTIFIERS:
            vague_identifier_count += 1
        if len(lower) <= 2 and lower not in _COMPLEXITY_ALLOWED_SHORT_IDENTIFIERS and not lower.startswith("__"):
            short_identifier_count += 1
    return {
        "short_identifier_count": short_identifier_count,
        "vague_identifier_count": vague_identifier_count,
        "naming_noise": round(short_identifier_count * 0.25 + vague_identifier_count * 1.5, 3),
    }


def _complexity_line_shape_component(text: str) -> dict[str, Any]:
    over_100 = 0
    over_140 = 0
    line_shape = 0.0
    max_line_length = 0
    for line in text.splitlines():
        length = len(line)
        max_line_length = max(max_line_length, length)
        if length > 100:
            over_100 += 1
            line_shape += 2.0 + (length - 100) / 20.0
        if length > 140:
            over_140 += 1
            line_shape += 6.0 + ((length - 140) ** 2) / 500.0
    return {"lines_over_100": over_100, "lines_over_140": over_140, "max_line_length": max_line_length, "line_shape": round(line_shape, 3)}


def _complexity_comment_balance_component(text: str, suffix: str) -> dict[str, Any]:
    if suffix not in _COMPLEXITY_CODE_SUFFIXES:
        return {"comment_line_count": 0, "comment_ratio": 0.0, "comment_balance": 0.0}
    nonempty_lines = [line for line in text.splitlines() if line.strip()]
    if len(nonempty_lines) < 80:
        return {"comment_line_count": 0, "comment_ratio": 0.0, "comment_balance": 0.0}
    comment_line_count = 0
    for line in nonempty_lines:
        stripped = line.strip()
        if stripped.startswith(("#", "//", "/*", "*", "*/")):
            comment_line_count += 1
    comment_ratio = comment_line_count / max(1, len(nonempty_lines))
    comment_balance = 0.0
    if comment_ratio < 0.02:
        comment_balance = (0.02 - comment_ratio) * len(nonempty_lines) * 1.5
    elif comment_ratio > 0.35:
        comment_balance = (comment_ratio - 0.35) * len(nonempty_lines) * 1.0
    return {"comment_line_count": comment_line_count, "comment_ratio": round(comment_ratio, 4), "comment_balance": round(comment_balance, 3)}


def _complexity_python_top_level_definition_count(text: str) -> int:
    try:
        module = ast.parse(text)
    except SyntaxError:
        return 0
    count = 0
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            count += 1
    return count



def _complexity_top_level_definition_count(text: str, suffix: str, function_records: list[dict[str, Any]]) -> int:
    if suffix in _PYTHON_EXTENSIONS:
        return _complexity_python_top_level_definition_count(text)
    if suffix in _C_EXTENSIONS or suffix in _BASH_EXTENSIONS:
        return len(function_records)
    return 0



def _complexity_file_architecture_component(text: str, suffix: str, function_records: list[dict[str, Any]]) -> dict[str, Any]:
    if suffix not in _COMPLEXITY_CODE_SUFFIXES:
        return {
            "file_line_count": len(text.splitlines()),
            "file_function_count": 0,
            "top_level_definition_count": 0,
            "file_architecture": 0.0,
            "architecture_flags": [],
        }
    line_count = len(text.splitlines())
    function_count = len(function_records)
    top_level_count = _complexity_top_level_definition_count(text, suffix, function_records)
    score = 0.0
    flags: list[str] = []
    if line_count > 1000:
        score += (line_count - 1000) / 10.0
        flags.append("large_file_over_1000_lines")
    if line_count > 3000:
        score += (line_count - 3000) / 4.0
        flags.append("godfile_over_3000_lines")
    if line_count > 10000:
        score += line_count - 10000
        flags.append("severe_godfile_over_10000_lines")
    if function_count > 80:
        score += (function_count - 80) * 1.5
        flags.append("many_functions_in_one_file")
    if function_count > 250:
        score += (function_count - 250) * 4.0
        flags.append("severe_function_concentration")
    if top_level_count > 80:
        score += (top_level_count - 80) * 1.0
        flags.append("many_top_level_definitions")
    if top_level_count > 250:
        score += (top_level_count - 250) * 3.0
        flags.append("severe_top_level_definition_concentration")
    return {
        "file_line_count": line_count,
        "file_function_count": function_count,
        "top_level_definition_count": top_level_count,
        "file_architecture": round(score, 3),
        "architecture_flags": flags,
    }


_COMPLEXITY_MODULE_ACTION_WORDS = {
    "add",
    "append",
    "apply",
    "build",
    "canonicalize",
    "collect",
    "command",
    "compact",
    "compute",
    "count",
    "create",
    "default",
    "discover",
    "emit",
    "ensure",
    "evaluate",
    "execute",
    "find",
    "handle",
    "latest",
    "list",
    "load",
    "materialize",
    "merge",
    "normalize",
    "open",
    "parse",
    "print",
    "propose",
    "read",
    "register",
    "render",
    "require",
    "resolve",
    "run",
    "save",
    "scan",
    "select",
    "sort",
    "summarize",
    "transform",
    "update",
    "validate",
    "verify",
    "write",
}

_COMPLEXITY_MODULE_TRAILING_WORDS = {
    "command",
    "commands",
    "entry",
    "entries",
    "file",
    "files",
    "handler",
    "handlers",
    "item",
    "items",
    "parser",
    "parsers",
    "path",
    "paths",
    "record",
    "records",
    "result",
    "results",
    "summaries",
    "summary",
}

_COMPLEXITY_MODULE_SPECIAL_PREFIXES = {
    ("complexity", "gate"): "complexity",
    ("complexity", "metric"): "complexity",
    ("complexity", "scan"): "complexity",
    ("hyor", "compact"): "hyor_compact",
    ("hyor", "controller"): "hyor_controller",
    ("hyor", "distribution"): "hyor_distribution",
    ("hyor", "executor"): "hyor_executor",
    ("hyor", "http"): "hyor_http",
    ("hyor", "model"): "hyor_model",
    ("hyor", "node"): "hyor_node",
    ("hyor", "provider"): "hyor_provider",
    ("hyor", "runtime"): "hyor_runtime",
    ("hyor", "spark"): "hyor_spark",
    ("hyor", "supervisor"): "hyor_supervisor",
    ("procedure", "complexity"): "procedure_complexity",
    ("procedure", "work"): "procedure_work",
    ("source", "map"): "source_map",
    ("test", "impact"): "test_impact",
    ("test", "run"): "test_run",
}

_COMPLEXITY_MODULE_DOMAIN_WORDS = {
    "artifact",
    "benchmark",
    "centaur",
    "complexity",
    "dry",
    "evolution",
    "model",
    "piece",
    "procedure",
    "project",
    "shorthand",
    "source",
    "spark",
    "state",
    "test",
    "tool",
}


def _complexity_identifier_words(identifier: str) -> list[str]:
    return _split_identifier_words(identifier)


def _complexity_module_key_for_function_name(function_name: str) -> str:
    words = _complexity_identifier_words(function_name)
    while words and words[0] in _COMPLEXITY_MODULE_ACTION_WORDS:
        words = words[1:]
    while words and words[-1] in _COMPLEXITY_MODULE_TRAILING_WORDS:
        words = words[:-1]
    if not words:
        return "misc"
    if len(words) >= 2 and tuple(words[:2]) in _COMPLEXITY_MODULE_SPECIAL_PREFIXES:
        return _COMPLEXITY_MODULE_SPECIAL_PREFIXES[tuple(words[:2])]
    if words[0] == "hyor" and len(words) >= 2:
        return "_".join(words[:2])
    if words[0] in _COMPLEXITY_MODULE_DOMAIN_WORDS:
        return words[0]
    if len(words) >= 2:
        return "_".join(words[:2])
    return words[0]


def _complexity_python_top_level_function_nodes(text: str) -> dict[str, ast.AST]:
    try:
        module = ast.parse(text)
    except SyntaxError:
        return {}
    functions: dict[str, ast.AST] = {}
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
    return functions


def _complexity_python_function_call_names(node: ast.AST, defined_names: set[str]) -> list[str]:
    names: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in defined_names:
            names.append(child.func.id)
    return names


def _complexity_module_cluster_effect_summary(names: list[str], function_nodes: dict[str, ast.AST]) -> dict[str, Any]:
    domains: set[str] = set()
    concurrency_touchpoints = 0
    for name in names:
        node = function_nodes.get(name)
        if node is None:
            continue
        domains.update(_complexity_python_side_effect_domains(node))
        concurrency_touchpoints += _complexity_python_concurrency_touchpoint_count(node)
    return {
        "side_effect_domains": sorted(domains),
        "side_effect_domain_count": len(domains),
        "concurrency_touchpoint_count": concurrency_touchpoints,
    }


def _complexity_module_candidate_pressure(function_count: int, api_ratio: float, internal_calls: int, cross_calls: int, line_count: int, side_effect_count: int, concurrency_touchpoints: int) -> float:
    if function_count < 6:
        return 0.0
    small_api_bonus = max(0.0, 0.70 - api_ratio) * 2.0
    cluster_pressure = max(0, function_count - 5) * (0.5 + small_api_bonus)
    call_cohesion = max(0, internal_calls - cross_calls // 2) * 0.25
    line_pressure = max(0, line_count - 120) / 80.0
    effect_pressure = side_effect_count * 1.25 + concurrency_touchpoints * 4.0
    return round(cluster_pressure + call_cohesion + line_pressure + effect_pressure, 3)


def _complexity_module_cluster_complexity(function_count: int, api_count: int, line_count: int, cross_calls: int, side_effect_count: int, concurrency_touchpoints: int) -> float:
    api_pressure = api_count * api_count * 0.75
    state_pressure = side_effect_count * 4.0 + concurrency_touchpoints * 10.0
    return round(function_count + line_count / 60.0 + cross_calls * 1.5 + api_pressure + state_pressure, 3)


def _complexity_summarize_module_cluster(
    module_key: str,
    names: list[str],
    function_nodes: dict[str, ast.AST],
    function_calls: dict[str, list[str]],
    relative_path: str,
) -> dict[str, Any]:
    name_set = set(names)
    internal_called: set[str] = set()
    inbound_called: set[str] = set()
    internal_calls = 0
    outbound_calls = 0
    inbound_calls = 0
    for name in names:
        for called in function_calls.get(name, []):
            if called in name_set:
                internal_calls += 1
                internal_called.add(called)
            else:
                outbound_calls += 1
    for caller, called_names in function_calls.items():
        if caller in name_set:
            continue
        for called in called_names:
            if called in name_set:
                inbound_calls += 1
                inbound_called.add(called)
    entrypoints = sorted(name for name in names if name not in internal_called or name in inbound_called)
    public_entrypoints = [name for name in entrypoints if not name.startswith("_")]
    if not public_entrypoints and names and not all(name.startswith("_") for name in names):
        public_entrypoints = [name for name in sorted(names) if not name.startswith("_")][:1]
    line_count = sum(_complexity_python_function_line_count(function_nodes[name]) for name in names)
    api_ratio = round(len(public_entrypoints) / max(1, len(names)), 6)
    effects = _complexity_module_cluster_effect_summary(names, function_nodes)
    cross_calls = outbound_calls + inbound_calls
    pressure = _complexity_module_candidate_pressure(len(names), api_ratio, internal_calls, cross_calls, line_count, int(effects["side_effect_domain_count"]), int(effects["concurrency_touchpoint_count"]))
    module_score = _complexity_module_cluster_complexity(len(names), len(public_entrypoints), line_count, cross_calls, int(effects["side_effect_domain_count"]), int(effects["concurrency_touchpoint_count"]))
    return {
        "relative_path": relative_path,
        "module_key": module_key,
        "function_count": len(names),
        "line_count": line_count,
        "api_function_count": len(public_entrypoints),
        "api_to_function_ratio": api_ratio,
        "internal_call_count": internal_calls,
        "outbound_call_count": outbound_calls,
        "inbound_call_count": inbound_calls,
        "cross_call_count": cross_calls,
        "side_effect_domains": effects["side_effect_domains"],
        "side_effect_domain_count": effects["side_effect_domain_count"],
        "concurrency_touchpoint_count": effects["concurrency_touchpoint_count"],
        "module_complexity_score": module_score,
        "new_module_cost": 8.0,
        "boundary_pressure": pressure,
        "net_boundary_benefit": round(max(0.0, pressure - 8.0), 3),
        "api_function_names": public_entrypoints[:25],
        "representative_function_names": sorted(names)[:25],
    }


def _complexity_python_function_line_count(node: ast.AST) -> int:
    start_line = int(getattr(node, "lineno", 1))
    end_line = int(getattr(node, "end_lineno", start_line))
    return max(1, end_line - start_line + 1)


def _neutral_complexity_module_boundary_component() -> dict[str, Any]:
    return {
        "module_boundary": 0.0,
        "module_candidate_count": 0,
        "max_module_candidate_function_count": 0,
        "min_module_candidate_api_ratio": 1.0,
        "module_boundary_candidates": [],
        "module_cluster_count": 0,
        "large_module_cluster_count": 0,
        "extractable_module_count": 0,
        "module_cluster_entropy": 0.0,
        "public_api_function_count": 0,
        "largest_module_cluster_function_count": 0,
        "project_module_complexity_score": 0.0,
        "cross_module_call_count": 0,
        "side_effect_domain_count": 0,
        "concurrency_module_count": 0,
        "module_clusters": [],
        "modularization_candidates": [],
    }


def _complexity_python_cluster_entropy(clusters: dict[str, list[str]]) -> float:
    total = sum(len(names) for names in clusters.values())
    if total <= 0:
        return 0.0
    entropy = 0.0
    for names in clusters.values():
        proportion = len(names) / total
        if proportion > 0.0:
            entropy -= proportion * math.log2(proportion)
    return round(entropy, 6)


def _select_complexity_module_boundary_candidates(candidates: list[dict[str, Any]], cluster_count: int, line_count: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        function_count = int(candidate.get("function_count", 0) or 0)
        api_count = int(candidate.get("api_function_count", 0) or 0)
        api_limit = max(2, int(math.ceil(function_count * 0.40)))
        has_real_boundary = cluster_count > 1 or line_count > 1000 or function_count >= 20
        if has_real_boundary and function_count >= 6 and api_count <= api_limit:
            selected.append(candidate)
    return selected


def _complexity_python_module_boundary_component(text: str, relative_path: str) -> dict[str, Any]:
    function_nodes = _complexity_python_top_level_function_nodes(text)
    if len(function_nodes) < 6:
        return _neutral_complexity_module_boundary_component()
    defined_names = set(function_nodes)
    function_calls = {name: _complexity_python_function_call_names(node, defined_names) for name, node in function_nodes.items()}
    clusters: dict[str, list[str]] = {}
    for name in sorted(function_nodes):
        clusters.setdefault(_complexity_module_key_for_function_name(name), []).append(name)
    cluster_rows = [_complexity_summarize_module_cluster(key, names, function_nodes, function_calls, relative_path) for key, names in sorted(clusters.items()) if len(names) >= 3]
    large_cluster_rows = [row for row in cluster_rows if int(row.get("function_count", 0) or 0) >= 6]
    pressure_rows = [row for row in large_cluster_rows if float(row.get("boundary_pressure", 0.0)) > 0.0]
    extractable_rows = _select_complexity_module_boundary_candidates(pressure_rows, len(clusters), len(text.splitlines()))
    side_effect_domains = {domain for row in cluster_rows for domain in row.get("side_effect_domains", []) if isinstance(domain, str)}
    return {
        "module_boundary": round(sum(float(row.get("boundary_pressure", 0.0)) for row in extractable_rows), 3),
        "module_candidate_count": len(extractable_rows),
        "max_module_candidate_function_count": max((int(row.get("function_count", 0)) for row in extractable_rows), default=0),
        "min_module_candidate_api_ratio": min((float(row.get("api_to_function_ratio", 1.0)) for row in extractable_rows), default=1.0),
        "module_boundary_candidates": extractable_rows[:12],
        "module_cluster_count": len(clusters),
        "large_module_cluster_count": len(large_cluster_rows),
        "extractable_module_count": len(extractable_rows),
        "module_cluster_entropy": _complexity_python_cluster_entropy(clusters),
        "public_api_function_count": sum(int(row.get("api_function_count", 0) or 0) for row in large_cluster_rows),
        "largest_module_cluster_function_count": max((len(names) for names in clusters.values()), default=0),
        "project_module_complexity_score": round(sum(float(row.get("module_complexity_score", 0.0)) for row in cluster_rows), 3),
        "cross_module_call_count": sum(int(row.get("cross_call_count", 0) or 0) for row in cluster_rows),
        "side_effect_domain_count": len(side_effect_domains),
        "concurrency_module_count": sum(1 for row in cluster_rows if int(row.get("concurrency_touchpoint_count", 0) or 0) > 0),
        "module_clusters": cluster_rows[:16],
        "modularization_candidates": extractable_rows[:12],
    }


def _complexity_module_boundary_component(text: str, suffix: str, relative_path: str) -> dict[str, Any]:
    if suffix not in _PYTHON_EXTENSIONS:
        return _neutral_complexity_module_boundary_component()
    return _complexity_python_module_boundary_component(text, relative_path)



def _complexity_function_size_component(function_records: list[dict[str, Any]]) -> dict[str, Any]:
    function_size = 0.0
    functions_over_50 = 0
    functions_over_100 = 0
    max_function_lines = 0
    for record in function_records:
        line_count = int(record.get("line_count", 0))
        max_function_lines = max(max_function_lines, line_count)
        if line_count > 50:
            functions_over_50 += 1
            function_size += 10.0 + ((line_count - 50) ** 2) / 32.0
        if line_count > 100:
            functions_over_100 += 1
            function_size += 50.0 + ((line_count - 100) ** 2) / 16.0
    return {
        "function_count": len(function_records),
        "functions_over_50": functions_over_50,
        "functions_over_100": functions_over_100,
        "max_function_lines": max_function_lines,
        "function_size": round(function_size, 3),
    }


def _complexity_function_state_component(function_records: list[dict[str, Any]]) -> dict[str, Any]:
    score = 0.0
    total_parameter_count = 0
    total_local_variable_count = 0
    total_exit_point_count = 0
    max_parameter_count = 0
    max_local_variable_count = 0
    max_exit_point_count = 0
    side_effect_function_count = 0
    concurrency_touchpoint_count = 0
    for record in function_records:
        parameter_count = int(record.get("parameter_count", 0) or 0)
        local_count = int(record.get("local_variable_count", record.get("local_name_count", 0)) or 0)
        exit_count = int(record.get("exit_point_count", 0) or 0)
        domains = record.get("side_effect_domains", record.get("side_effect_flags", []))
        domains = domains if isinstance(domains, list) else []
        concurrency_flags = record.get("concurrency_flags") if isinstance(record.get("concurrency_flags"), list) else []
        concurrency_count = int(record.get("concurrency_touchpoint_count", len(concurrency_flags)) or 0)
        total_parameter_count += parameter_count
        total_local_variable_count += local_count
        total_exit_point_count += exit_count
        max_parameter_count = max(max_parameter_count, parameter_count)
        max_local_variable_count = max(max_local_variable_count, local_count)
        max_exit_point_count = max(max_exit_point_count, exit_count)
        side_effect_function_count += 1 if domains else 0
        concurrency_touchpoint_count += concurrency_count
        score += max(0, parameter_count - 5) ** 2 * 1.5
        score += max(0, local_count - 12) ** 2 * 0.75
        score += max(0, exit_count - 4) ** 2 * 1.25
        score += len(domains) * 1.5 + concurrency_count * 6.0
    return {
        "function_state": round(score, 3),
        "total_parameter_count": total_parameter_count,
        "max_parameter_count": max_parameter_count,
        "total_local_variable_count": total_local_variable_count,
        "max_local_variable_count": max_local_variable_count,
        "total_exit_point_count": total_exit_point_count,
        "max_exit_point_count": max_exit_point_count,
        "side_effect_function_count": side_effect_function_count,
        "concurrency_touchpoint_count": concurrency_touchpoint_count,
    }


def _complexity_branching_component(text: str, suffix: str, function_records: list[dict[str, Any]]) -> dict[str, Any]:
    if function_records:
        cyclomatic_sum = sum(int(record.get("cyclomatic", 0)) for record in function_records)
        max_function_cyclomatic = max((int(record.get("cyclomatic", 0)) for record in function_records), default=0)
    elif suffix in _COMPLEXITY_CODE_SUFFIXES:
        cyclomatic_sum = max(1, _count_generic_decision_points(text))
        max_function_cyclomatic = cyclomatic_sum
    else:
        cyclomatic_sum = 0
        max_function_cyclomatic = 0
    branching = 2.0 * cyclomatic_sum + 4.0 * max(0, max_function_cyclomatic - 10)
    return {"cyclomatic_sum": cyclomatic_sum, "max_function_cyclomatic": max_function_cyclomatic, "branching": round(branching, 3)}


def _complexity_nesting_component(function_records: list[dict[str, Any]]) -> dict[str, Any]:
    max_nesting_depth = max((int(record.get("nesting_depth", 0)) for record in function_records), default=0)
    nesting = 0.0
    for record in function_records:
        depth = int(record.get("nesting_depth", 0))
        if depth > 4:
            nesting += ((depth - 4) ** 2) * 6.0
    if max_nesting_depth > 4:
        nesting += (max_nesting_depth - 4) * 4.0
    return {"max_nesting_depth": max_nesting_depth, "nesting": round(nesting, 3)}


def _neutral_complexity_module_interface_component() -> dict[str, Any]:
    return {
        "module_interface": 0.0,
        "module_public_api_count": 0,
        "module_declared_public_api_count": 0,
        "module_leaked_public_name_count": 0,
        "module_missing_declared_api_count": 0,
        "module_uses_declared_public_api": False,
        "module_public_function_count": 0,
        "module_public_class_count": 0,
        "module_public_value_count": 0,
        "module_visible_value_count": 0,
        "module_leaked_public_value_count": 0,
        "module_public_parameter_count": 0,
        "module_max_public_parameter_count": 0,
        "module_mutable_global_count": 0,
        "module_import_time_call_count": 0,
        "module_side_effect_function_count": 0,
        "module_public_side_effect_api_count": 0,
        "module_concurrency_function_count": 0,
        "module_public_concurrency_api_count": 0,
        "module_interface_flags": [],
    }


def _complexity_python_string_sequence_literal(node: ast.AST) -> Optional[set[str]]:
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return None
    names: set[str] = set()
    for item in node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        names.add(item.value)
    return names


def _complexity_python_named_string_sequences(module: ast.Module) -> dict[str, set[str]]:
    sequences: dict[str, set[str]] = {}
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        literal = _complexity_python_string_sequence_literal(node.value)
        if literal is not None:
            sequences[target.id] = literal
    return sequences


def _complexity_python_declared_public_api_names(module: ast.Module) -> Optional[set[str]]:
    sequences = _complexity_python_named_string_sequences(module)
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        target_names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        if "__all__" not in target_names:
            continue
        literal = _complexity_python_string_sequence_literal(node.value)
        if literal is not None:
            return literal
        if isinstance(node.value, ast.Name) and node.value.id in sequences:
            return set(sequences[node.value.id])
    return None


def _complexity_module_name_for_python_path(path: Path, root: Path) -> Optional[str]:
    if path.suffix != ".py":
        return None
    relative_path = path.relative_to(root) if _path_inside(path, root) else Path(path.name)
    parts = list(relative_path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    return ".".join(parts)


def _complexity_declared_api_by_module(files: list[Path], root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in files:
        module_name = _complexity_module_name_for_python_path(path, root)
        if module_name is None:
            continue
        try:
            module = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        declared_names = _complexity_python_declared_public_api_names(module)
        if declared_names is None:
            continue
        result[module_name] = {
            "relative_path": path.relative_to(root).as_posix() if _path_inside(path, root) else path.name,
            "public_names": set(declared_names),
        }
    return result


def _complexity_importer_package_parts(path: Path, root: Path) -> list[str]:
    module_name = _complexity_module_name_for_python_path(path, root)
    if module_name is None:
        return []
    parts = module_name.split(".")
    return parts if path.name == "__init__.py" else parts[:-1]


def _complexity_imported_module_name(node: ast.ImportFrom, path: Path, root: Path) -> Optional[str]:
    if node.level <= 0:
        return node.module
    package_parts = _complexity_importer_package_parts(path, root)
    keep_count = max(0, len(package_parts) - node.level + 1)
    parts = package_parts[:keep_count]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts) if parts else None


def _complexity_api_boundary_violations_for_file(path: Path, root: Path, declared_api_by_module: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if path.suffix != ".py":
        return []
    try:
        module = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    violations: list[dict[str, Any]] = []
    importing_file = path.relative_to(root).as_posix() if _path_inside(path, root) else path.name
    for node in ast.walk(module):
        if not isinstance(node, ast.ImportFrom):
            continue
        imported_module = _complexity_imported_module_name(node, path, root)
        api_record = declared_api_by_module.get(imported_module or "")
        if api_record is None:
            continue
        public_names = api_record.get("public_names") if isinstance(api_record.get("public_names"), set) else set()
        for alias in node.names:
            if alias.name == "*" or alias.name in public_names:
                continue
            violations.append({
                "kind": "module_api_boundary_violation",
                "importing_file": importing_file,
                "imported_module": imported_module,
                "module_path": api_record.get("relative_path"),
                "imported_name": alias.name,
                "line_number": int(getattr(node, "lineno", 0) or 0),
            })
    return violations


def _build_complexity_api_boundary_report(files: list[Path], root: Path) -> dict[str, Any]:
    declared_api_by_module = _complexity_declared_api_by_module(files, root)
    violations: list[dict[str, Any]] = []
    for path in files:
        violations.extend(_complexity_api_boundary_violations_for_file(path, root, declared_api_by_module))
    violations.sort(key=lambda item: (str(item.get("importing_file", "")), int(item.get("line_number", 0)), str(item.get("imported_name", ""))))
    return {
        "module_api_boundary_violation_count": len(violations),
        "module_api_boundary_violations": violations[:25],
    }


def _complexity_python_visible_module_names(module: ast.Module) -> tuple[set[str], set[str], set[str]]:
    visible_functions: set[str] = set()
    visible_classes: set[str] = set()
    visible_values: set[str] = set()
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            visible_functions.add(node.name)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            visible_classes.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_") and target.id != "__all__":
                    visible_values.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not node.target.id.startswith("_") and node.target.id != "__all__":
                visible_values.add(node.target.id)
    return visible_functions, visible_classes, visible_values

def _complexity_python_module_public_names(module: ast.Module) -> tuple[set[str], set[str], set[str]]:
    visible_functions, visible_classes, visible_values = _complexity_python_visible_module_names(module)
    declared_names = _complexity_python_declared_public_api_names(module)
    if declared_names is None:
        return visible_functions, visible_classes, visible_values
    return visible_functions & declared_names, visible_classes & declared_names, visible_values & declared_names

def _complexity_python_top_level_mutable_global_count(module: ast.Module) -> int:
    count = 0
    for node in module.body:
        value = getattr(node, "value", None)
        targets = getattr(node, "targets", None)
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if not isinstance(targets, list):
            continue
        names = {target.id for target in targets if isinstance(target, ast.Name)}
        if names and not all(name.isupper() for name in names):
            if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp, ast.Call)):
                count += len(names)
    return count


def _complexity_python_top_level_call_count(module: ast.Module) -> int:
    count = 0
    for node in module.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            count += 1
    return count


def _complexity_module_interface_score(public_api_count: int, public_parameter_count: int, max_public_parameters: int, mutable_global_count: int, import_time_call_count: int, public_side_effect_count: int, public_concurrency_count: int, internal_side_effect_count: int, internal_concurrency_count: int, leaked_public_name_count: int, missing_declared_name_count: int) -> float:
    score = max(0, public_api_count - 12) * 1.5 + max(0, public_api_count - 40) * 2.5
    score += leaked_public_name_count * 0.8 + max(0, leaked_public_name_count - 20) * 0.75
    score += max(0, leaked_public_name_count - 80) * 1.25 + missing_declared_name_count * 2.0
    score += max(0, public_parameter_count - public_api_count * 3) * 0.25
    score += max(0, max_public_parameters - 5) * 3.0
    score += mutable_global_count * 5.0 + import_time_call_count * 8.0
    score += public_side_effect_count * 8.0 + internal_side_effect_count * 1.25
    score += public_concurrency_count * 18.0 + max(0, public_concurrency_count - 2) * 24.0
    score += internal_concurrency_count * 3.0
    return round(score, 3)

def _complexity_record_side_effect_domains(record: dict[str, Any]) -> list[str]:
    domains = record.get("side_effect_domains") if isinstance(record.get("side_effect_domains"), list) else record.get("side_effect_flags", [])
    return domains if isinstance(domains, list) else []


def _complexity_record_concurrency_touchpoints(record: dict[str, Any]) -> int:
    flags = record.get("concurrency_flags") if isinstance(record.get("concurrency_flags"), list) else []
    return int(record.get("concurrency_touchpoint_count", len(flags)) or 0)


def _complexity_python_module_interface_component(text: str, function_records: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        module = ast.parse(text)
    except SyntaxError:
        return _neutral_complexity_module_interface_component()
    visible_functions, visible_classes, visible_values = _complexity_python_visible_module_names(module)
    declared_names = _complexity_python_declared_public_api_names(module)
    public_functions, public_classes, public_values = _complexity_python_module_public_names(module)
    visible_names = visible_functions | visible_classes | visible_values
    if declared_names is None:
        leaked_names: set[str] = set()
        missing_declared_names: set[str] = set()
        public_api_count = len(visible_names)
    else:
        leaked_names = visible_names - declared_names
        missing_declared_names = declared_names - visible_names
        public_api_count = len(declared_names)
    public_records = [record for record in function_records if str(record.get("name", "")) in public_functions]
    public_parameter_count = sum(int(record.get("parameter_count", 0) or 0) for record in public_records)
    max_public_parameters = max((int(record.get("parameter_count", 0) or 0) for record in public_records), default=0)
    public_side_effect_count = sum(1 for record in public_records if _complexity_record_side_effect_domains(record))
    public_concurrency_count = sum(1 for record in public_records if _complexity_record_concurrency_touchpoints(record) > 0)
    side_effect_count = sum(1 for record in function_records if _complexity_record_side_effect_domains(record))
    concurrency_count = sum(1 for record in function_records if _complexity_record_concurrency_touchpoints(record) > 0)
    mutable_global_count = _complexity_python_top_level_mutable_global_count(module)
    import_time_call_count = _complexity_python_top_level_call_count(module)
    leaked_public_name_count = len(leaked_names)
    score = _complexity_module_interface_score(public_api_count, public_parameter_count, max_public_parameters, mutable_global_count, import_time_call_count, public_side_effect_count, public_concurrency_count, max(0, side_effect_count - public_side_effect_count), max(0, concurrency_count - public_concurrency_count), leaked_public_name_count, len(missing_declared_names))
    flags: list[str] = []
    if public_api_count > 40:
        flags.append("wide_public_api")
    if leaked_public_name_count > 0:
        flags.append("non_api_public_names_not_hidden")
    if missing_declared_names:
        flags.append("declared_api_names_missing")
    if public_concurrency_count > 2:
        flags.append("concurrency_leaks_through_public_api")
    if public_side_effect_count > 10:
        flags.append("side_effect_heavy_public_api")
    if mutable_global_count > 10:
        flags.append("mutable_global_state_surface")
    if score > 0.0 and not flags:
        flags.append("module_interface_pressure")
    return {
        "module_interface": score,
        "module_public_api_count": public_api_count,
        "module_declared_public_api_count": len(declared_names) if declared_names is not None else 0,
        "module_leaked_public_name_count": leaked_public_name_count,
        "module_missing_declared_api_count": len(missing_declared_names),
        "module_uses_declared_public_api": declared_names is not None,
        "module_public_function_count": len(public_functions),
        "module_public_class_count": len(public_classes),
        "module_public_value_count": len(public_values),
        "module_visible_value_count": len(visible_values),
        "module_leaked_public_value_count": len(leaked_names & visible_values),
        "module_public_parameter_count": public_parameter_count,
        "module_max_public_parameter_count": max_public_parameters,
        "module_mutable_global_count": mutable_global_count,
        "module_import_time_call_count": import_time_call_count,
        "module_side_effect_function_count": side_effect_count,
        "module_public_side_effect_api_count": public_side_effect_count,
        "module_concurrency_function_count": concurrency_count,
        "module_public_concurrency_api_count": public_concurrency_count,
        "module_interface_flags": flags,
    }

def _complexity_module_interface_component(text: str, suffix: str, function_records: list[dict[str, Any]]) -> dict[str, Any]:
    if suffix not in _PYTHON_EXTENSIONS:
        return _neutral_complexity_module_interface_component()
    return _complexity_python_module_interface_component(text, function_records)


def _add_complexity_source_file_report_details(report: dict[str, Any], function_records: list[dict[str, Any]], component_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    function_size = component_reports["function_size"]
    branching = component_reports["branching"]
    nesting = component_reports["nesting"]
    duplication = component_reports["duplication"]
    naming_noise = component_reports["naming_noise"]
    line_shape = component_reports["line_shape"]
    comment_balance = component_reports["comment_balance"]
    report.update({
        "max_function_lines": function_size["max_function_lines"],
        "functions_over_50": function_size["functions_over_50"],
        "functions_over_100": function_size["functions_over_100"],
        "cyclomatic_sum": branching["cyclomatic_sum"],
        "max_function_cyclomatic": branching["max_function_cyclomatic"],
        "max_nesting_depth": nesting["max_nesting_depth"],
        "repeated_normalized_blocks": duplication["repeated_normalized_blocks"],
        "repeated_block_byte_estimate": duplication["repeated_block_byte_estimate"],
        "duplicate_block_examples": duplication["duplicate_block_examples"],
        "short_identifier_count": naming_noise["short_identifier_count"],
        "vague_identifier_count": naming_noise["vague_identifier_count"],
        "lines_over_100": line_shape["lines_over_100"],
        "lines_over_140": line_shape["lines_over_140"],
        "max_line_length": line_shape["max_line_length"],
        "comment_line_count": comment_balance["comment_line_count"],
        "comment_ratio": comment_balance["comment_ratio"],
    })
    if function_records:
        report["largest_functions"] = sorted(function_records, key=lambda item: (-int(item.get("line_count", 0)), str(item.get("name", "")), int(item.get("line", 0))))[:10]
    return report


def _build_complexity_source_file_report(
    path: Path,
    root: Path,
    data: bytes,
    canonical: str,
    text: str,
    function_records: list[dict[str, Any]],
    components: dict[str, float],
    component_reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    function_size = component_reports["function_size"]
    function_state = component_reports["function_state"]
    file_architecture = component_reports["file_architecture"]
    module_interface = component_reports["module_interface"]
    module_boundary = component_reports["module_boundary"]
    relative_path = path.relative_to(root).as_posix() if _path_inside(path, root) else path.name
    report: dict[str, Any] = {
        "path": str(path),
        "relative_path": relative_path,
        "score": round(sum(float(components[name]) for name in _COMPLEXITY_COMPONENT_NAMES), 3),
        "components": components,
        "raw_size_bytes": len(data),
        "canonical_size_bytes": len(canonical.encode("utf-8", errors="replace")),
        "canonical_sha256": _sha256_bytes(canonical.encode("utf-8", errors="replace")),
        "line_count": len(text.splitlines()),
        "function_count": function_size["function_count"],
        "function_state_score": function_state["function_state"],
        "total_parameter_count": function_state["total_parameter_count"],
        "max_parameter_count": function_state["max_parameter_count"],
        "total_local_variable_count": function_state["total_local_variable_count"],
        "max_local_variable_count": function_state["max_local_variable_count"],
        "total_exit_point_count": function_state["total_exit_point_count"],
        "max_exit_point_count": function_state["max_exit_point_count"],
        "side_effect_function_count": function_state["side_effect_function_count"],
        "concurrency_touchpoint_count": function_state["concurrency_touchpoint_count"],
        "file_architecture_score": file_architecture["file_architecture"],
        "architecture_flags": file_architecture["architecture_flags"],
        "top_level_definition_count": file_architecture["top_level_definition_count"],
        "module_interface_score": module_interface["module_interface"],
        "module_public_api_count": module_interface["module_public_api_count"],
        "module_declared_public_api_count": module_interface["module_declared_public_api_count"],
        "module_leaked_public_name_count": module_interface["module_leaked_public_name_count"],
        "module_missing_declared_api_count": module_interface["module_missing_declared_api_count"],
        "module_uses_declared_public_api": module_interface["module_uses_declared_public_api"],
        "module_public_function_count": module_interface["module_public_function_count"],
        "module_public_class_count": module_interface["module_public_class_count"],
        "module_public_value_count": module_interface["module_public_value_count"],
        "module_visible_value_count": module_interface["module_visible_value_count"],
        "module_leaked_public_value_count": module_interface["module_leaked_public_value_count"],
        "module_public_parameter_count": module_interface["module_public_parameter_count"],
        "module_max_public_parameter_count": module_interface["module_max_public_parameter_count"],
        "module_mutable_global_count": module_interface["module_mutable_global_count"],
        "module_import_time_call_count": module_interface["module_import_time_call_count"],
        "module_side_effect_function_count": module_interface["module_side_effect_function_count"],
        "module_public_side_effect_api_count": module_interface["module_public_side_effect_api_count"],
        "module_concurrency_function_count": module_interface["module_concurrency_function_count"],
        "module_public_concurrency_api_count": module_interface["module_public_concurrency_api_count"],
        "module_interface_flags": module_interface["module_interface_flags"],
        "module_boundary_score": module_boundary["module_boundary"],
        "module_cluster_count": module_boundary["module_cluster_count"],
        "large_module_cluster_count": module_boundary["large_module_cluster_count"],
        "extractable_module_count": module_boundary["extractable_module_count"],
        "module_cluster_entropy": module_boundary["module_cluster_entropy"],
        "public_api_function_count": module_boundary["public_api_function_count"],
        "largest_module_cluster_function_count": module_boundary["largest_module_cluster_function_count"],
        "project_module_complexity_score": module_boundary.get("project_module_complexity_score", 0.0),
        "cross_module_call_count": module_boundary.get("cross_module_call_count", 0),
        "module_side_effect_domain_count": module_boundary.get("side_effect_domain_count", 0),
        "concurrency_module_count": module_boundary.get("concurrency_module_count", 0),
    }
    report.update({
        "module_clusters": module_boundary["module_clusters"],
        "modularization_candidates": module_boundary["modularization_candidates"],
        "module_candidate_count": module_boundary.get("module_candidate_count", 0),
        "max_module_candidate_function_count": module_boundary.get("max_module_candidate_function_count", 0),
        "min_module_candidate_api_ratio": module_boundary.get("min_module_candidate_api_ratio", 1.0),
        "module_boundary_candidates": module_boundary.get("module_boundary_candidates", []),
    })
    return _add_complexity_source_file_report_details(report, function_records, component_reports)


def _complexity_complexity_source_file(path: Path, root: Path) -> dict[str, Any]:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    suffix = path.suffix.lower()
    canonical = canonicalize_text_for_complexity(text)
    function_records = _complexity_function_records_for_source(text, suffix)
    relative_path = path.relative_to(root).as_posix() if _path_inside(path, root) else path.name
    compressed_load = len(gzip.compress(canonical.encode("utf-8", errors="replace"), compresslevel=9)) / 1024.0 if canonical else 0.0
    component_reports = {
        "branching": _complexity_branching_component(text, suffix, function_records),
        "function_size": _complexity_function_size_component(function_records),
        "function_state": _complexity_function_state_component(function_records),
        "nesting": _complexity_nesting_component(function_records),
        "duplication": _complexity_duplication_component(text),
        "naming_noise": _complexity_naming_noise_component(text, suffix),
        "line_shape": _complexity_line_shape_component(text),
        "file_architecture": _complexity_file_architecture_component(text, suffix, function_records),
        "module_interface": _complexity_module_interface_component(text, suffix, function_records),
        "module_boundary": _complexity_module_boundary_component(text, suffix, relative_path),
        "comment_balance": _complexity_comment_balance_component(text, suffix),
    }
    components = {
        "compressed_load": round(compressed_load, 3),
        "branching": component_reports["branching"]["branching"],
        "function_size": component_reports["function_size"]["function_size"],
        "function_state": component_reports["function_state"]["function_state"],
        "nesting": component_reports["nesting"]["nesting"],
        "duplication": round(float(component_reports["duplication"]["duplication"]), 3),
        "naming_noise": component_reports["naming_noise"]["naming_noise"],
        "line_shape": component_reports["line_shape"]["line_shape"],
        "file_architecture": component_reports["file_architecture"]["file_architecture"],
        "module_interface": component_reports["module_interface"]["module_interface"],
        "module_boundary": component_reports["module_boundary"]["module_boundary"],
        "comment_balance": component_reports["comment_balance"]["comment_balance"],
    }
    return _build_complexity_source_file_report(path, root, data, canonical, text, function_records, components, component_reports)


def _build_complexity_architecture_findings(reports: list[dict[str, Any]], total_line_count: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for report in reports:
        flags = report.get("architecture_flags") if isinstance(report.get("architecture_flags"), list) else []
        if not flags:
            continue
        line_count = int(report.get("line_count", 0) or 0)
        function_count = int(report.get("function_count", 0) or 0)
        finding = {
            "kind": "file_architecture",
            "severity": "blocker" if "severe_godfile_over_10000_lines" in flags or "severe_function_concentration" in flags else "warning",
            "relative_path": report.get("relative_path"),
            "line_count": line_count,
            "function_count": function_count,
            "line_share": round(line_count / total_line_count, 4) if total_line_count else 0.0,
            "score": report.get("file_architecture_score", 0.0),
            "flags": flags,
            "suggested_action": "split stable command families, report shaping, parser construction, and ledger helpers into separate modules",
        }
        findings.append(finding)
    findings.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("relative_path", ""))))
    return findings[:10]


def _build_complexity_duplication_findings(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for report in reports:
        repeated_blocks = int(report.get("repeated_normalized_blocks", 0) or 0)
        if repeated_blocks <= 0:
            continue
        examples = report.get("duplicate_block_examples")
        if not isinstance(examples, list):
            examples = []
        findings.append({
            "kind": "repeated_logic",
            "severity": "blocker" if repeated_blocks > 500 else "warning",
            "relative_path": report.get("relative_path"),
            "repeated_normalized_blocks": repeated_blocks,
            "repeated_block_byte_estimate": int(report.get("repeated_block_byte_estimate", 0) or 0),
            "examples": examples[:5],
            "suggested_action": "extract the repeated command/report/parser pattern into one shared builder",
        })
    findings.sort(key=lambda item: (-int(item.get("repeated_normalized_blocks", 0)), str(item.get("relative_path", ""))))
    return findings[:10]



def _build_complexity_module_boundary_findings(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for report in reports:
        candidates = report.get("module_boundary_candidates")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            api_ratio = float(candidate.get("api_to_function_ratio", 1.0) or 1.0)
            function_count = int(candidate.get("function_count", 0) or 0)
            pressure = float(candidate.get("boundary_pressure", 0.0) or 0.0)
            if function_count < 6 or pressure <= 0.0:
                continue
            findings.append({
                "kind": "module_boundary",
                "severity": "blocker" if function_count >= 40 and api_ratio <= 0.70 else "warning",
                "relative_path": candidate.get("relative_path"),
                "module_key": candidate.get("module_key"),
                "function_count": function_count,
                "line_count": int(candidate.get("line_count", 0) or 0),
                "api_function_count": int(candidate.get("api_function_count", 0) or 0),
                "api_to_function_ratio": api_ratio,
                "boundary_pressure": pressure,
                "net_boundary_benefit": candidate.get("net_boundary_benefit", 0.0),
                "module_complexity_score": candidate.get("module_complexity_score", 0.0),
                "side_effect_domains": candidate.get("side_effect_domains", []),
                "concurrency_touchpoint_count": candidate.get("concurrency_touchpoint_count", 0),
                "api_function_names": candidate.get("api_function_names", []),
                "suggested_action": "extract a capability module only after preserving this small public API surface",
            })
    findings.sort(key=lambda item: (-float(item.get("boundary_pressure", 0.0)), str(item.get("relative_path", "")), str(item.get("module_key", ""))))
    return findings[:15]

def _build_complexity_module_interface_findings(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for report in reports:
        score = float(report.get("module_interface_score", 0.0) or 0.0)
        flags = report.get("module_interface_flags") if isinstance(report.get("module_interface_flags"), list) else []
        if score <= 0.0 and not flags:
            continue
        public_api_count = int(report.get("module_public_api_count", 0) or 0)
        public_concurrency_count = int(report.get("module_public_concurrency_api_count", 0) or 0)
        public_side_effect_count = int(report.get("module_public_side_effect_api_count", 0) or 0)
        missing_declared_count = int(report.get("module_missing_declared_api_count", 0) or 0)
        severity = "blocker" if missing_declared_count > 0 or public_api_count > 100 or public_concurrency_count > 2 or public_side_effect_count > 50 else "warning"
        findings.append({
            "kind": "module_interface",
            "severity": severity,
            "relative_path": report.get("relative_path"),
            "score": score,
            "public_api_count": public_api_count,
            "declared_public_api_count": int(report.get("module_declared_public_api_count", 0) or 0),
            "leaked_public_name_count": int(report.get("module_leaked_public_name_count", 0) or 0),
            "missing_declared_api_count": missing_declared_count,
            "uses_declared_public_api": bool(report.get("module_uses_declared_public_api")),
            "public_side_effect_api_count": public_side_effect_count,
            "public_concurrency_api_count": public_concurrency_count,
            "mutable_global_count": int(report.get("module_mutable_global_count", 0) or 0),
            "flags": flags,
            "suggested_action": "reduce the preserved API, isolate side effects, and keep concurrency behind one narrow boundary",
        })
    findings.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("relative_path", ""))))
    return findings[:10]


def _build_complexity_api_boundary_findings(api_boundary_report: dict[str, Any]) -> list[dict[str, Any]]:
    violations = api_boundary_report.get("module_api_boundary_violations")
    if not isinstance(violations, list) or not violations:
        return []
    return [{
        "kind": "module_api_boundary",
        "severity": "blocker",
        "violation_count": int(api_boundary_report.get("module_api_boundary_violation_count", 0) or 0),
        "violations": violations[:10],
        "suggested_action": "route callers through the declared module API instead of importing internal helpers",
    }]


def _complexity_sum_report_int(reports: list[dict[str, Any]], key: str) -> int:
    return sum(int(report.get(key, 0) or 0) for report in reports)


def _complexity_max_report_int(reports: list[dict[str, Any]], key: str) -> int:
    return max((int(report.get(key, 0) or 0) for report in reports), default=0)


def _complexity_sum_report_float(reports: list[dict[str, Any]], key: str) -> float:
    return round(sum(float(report.get(key, 0.0) or 0.0) for report in reports), 3)


def _complexity_count_declared_api_modules(reports: list[dict[str, Any]]) -> int:
    return sum(1 for report in reports if bool(report.get("module_uses_declared_public_api")))


def _build_complexity_level_summary(components: dict[str, float], reports: list[dict[str, Any]], total_line_count: int, api_boundary_violation_count: int = 0) -> dict[str, Any]:
    function_score = sum(float(components.get(name, 0.0)) for name in ("branching", "function_size", "function_state", "nesting"))
    module_score = sum(float(components.get(name, 0.0)) for name in ("file_architecture", "module_interface", "module_boundary"))
    project_score = sum(float(components.get(name, 0.0)) for name in ("compressed_load", "duplication", "naming_noise", "line_shape", "comment_balance"))
    return {
        "function": {
            "score": round(function_score, 3),
            "max_parameters": _complexity_max_report_int(reports, "max_parameter_count"),
            "max_locals": _complexity_max_report_int(reports, "max_local_variable_count"),
            "max_function_lines": _complexity_max_report_int(reports, "max_function_lines"),
        },
        "module": {
            "score": round(module_score, 3),
            "public_api_count": _complexity_sum_report_int(reports, "module_public_api_count"),
            "declared_public_api_count": _complexity_sum_report_int(reports, "module_declared_public_api_count"),
            "leaked_public_name_count": _complexity_sum_report_int(reports, "module_leaked_public_name_count"),
            "missing_declared_api_count": _complexity_sum_report_int(reports, "module_missing_declared_api_count"),
            "public_value_count": _complexity_sum_report_int(reports, "module_public_value_count"),
            "public_parameter_count": _complexity_sum_report_int(reports, "module_public_parameter_count"),
            "max_public_parameter_count": _complexity_max_report_int(reports, "module_max_public_parameter_count"),
            "leaked_public_value_count": _complexity_sum_report_int(reports, "module_leaked_public_value_count"),
            "api_boundary_violation_count": api_boundary_violation_count,
            "declared_public_api_module_count": _complexity_count_declared_api_modules(reports),
            "candidate_count": _complexity_sum_report_int(reports, "module_candidate_count"),
            "public_concurrency_api_count": _complexity_sum_report_int(reports, "module_public_concurrency_api_count"),
        },
        "project": {
            "score": round(project_score, 3),
            "file_count": len(reports),
            "total_line_count": total_line_count,
            "repeated_normalized_blocks": _complexity_sum_report_int(reports, "repeated_normalized_blocks"),
        },
    }

def _product_scope_report_fields(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_scope_mode": selection.get("mode"),
        "included_file_count": selection.get("selected_file_count", 0),
        "excluded_file_count": selection.get("excluded_path_count", 0),
        "excluded_path_samples": selection.get("excluded_paths", [])[:25],
        "excluded_paths_truncated": selection.get("excluded_paths_truncated", False),
        "artifact_dir_exclusions": selection.get("artifact_dir_exclusions", {}),
    }


def scan_complexity(
    path: Path,
    limit: int = 25,
    full: bool = False,
    product_scope: str = "all",
    include_patterns: Optional[list[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
) -> dict[str, Any]:
    if limit < 0:
        raise ComplexityError("limit must be >= 0")
    resolved = path.resolve()
    root = resolved if resolved.is_dir() else resolved.parent
    scope_selection = select_product_scope_files(resolved, product_scope, include_patterns, exclude_patterns, text_only=True)
    files = [Path(item) for item in scope_selection["selected_paths"]]
    reports = [_complexity_complexity_source_file(item, root) for item in files]
    reports.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("relative_path", ""))))
    components = {name: round(sum(float(report.get("components", {}).get(name, 0.0)) for report in reports), 3) for name in _COMPLEXITY_COMPONENT_NAMES}
    api_boundary_report = _build_complexity_api_boundary_report(files, root)
    api_boundary_violation_count = int(api_boundary_report.get("module_api_boundary_violation_count", 0) or 0)
    if api_boundary_violation_count:
        components["module_interface"] = round(float(components.get("module_interface", 0.0)) + api_boundary_violation_count * 25.0, 3)
    top_reports = reports if limit == 0 else reports[:limit]
    total_line_count = sum(int(report.get("line_count", 0) or 0) for report in reports)
    max_file_lines = max((int(report.get("line_count", 0)) for report in reports), default=0)
    architecture_findings = _build_complexity_architecture_findings(reports, total_line_count)
    duplication_findings = _build_complexity_duplication_findings(reports)
    module_interface_findings = _build_complexity_module_interface_findings(reports)
    module_boundary_findings = _build_complexity_module_boundary_findings(reports)
    api_boundary_findings = _build_complexity_api_boundary_findings(api_boundary_report)
    complexity_levels = _build_complexity_level_summary(components, reports, total_line_count, api_boundary_violation_count)
    result: dict[str, Any] = {
        "format": _COMPLEXITY_SCAN_FORMAT,
        "status": "success",
        "version": 1,
        "profile_id": _DEFAULT_COMPLEXITY_PROFILE_ID,
        "direction": "lower_is_better",
        "path": str(resolved),
        "file_count": len(reports),
        "score": round(sum(float(components.get(name, 0.0)) for name in _COMPLEXITY_COMPONENT_NAMES), 3),
        "components": components,
        "max_function_lines": _complexity_max_report_int(reports, "max_function_lines"),
        "functions_over_50": _complexity_sum_report_int(reports, "functions_over_50"),
        "functions_over_100": _complexity_sum_report_int(reports, "functions_over_100"),
        "repeated_normalized_blocks": sum(int(report.get("repeated_normalized_blocks", 0)) for report in reports),
        "total_line_count": total_line_count,
        "max_file_lines": max_file_lines,
        "largest_file_line_share": round(max_file_lines / total_line_count, 4) if total_line_count else 0.0,
        "files_over_1000_lines": sum(1 for report in reports if int(report.get("line_count", 0) or 0) > 1000),
        "files_over_3000_lines": sum(1 for report in reports if int(report.get("line_count", 0) or 0) > 3000),
        "files_over_10000_lines": sum(1 for report in reports if int(report.get("line_count", 0) or 0) > 10000),
        "max_file_function_count": _complexity_max_report_int(reports, "function_count"),
        "files_over_250_functions": sum(1 for report in reports if int(report.get("function_count", 0) or 0) > 250),
        "module_candidate_count": _complexity_sum_report_int(reports, "module_candidate_count"),
        "max_module_candidate_function_count": _complexity_max_report_int(reports, "max_module_candidate_function_count"),
        "min_module_candidate_api_ratio": min((float(report.get("min_module_candidate_api_ratio", 1.0)) for report in reports if int(report.get("module_candidate_count", 0) or 0) > 0), default=1.0),
        "project_module_complexity_score": _complexity_sum_report_float(reports, "project_module_complexity_score"),
        "cross_module_call_count": _complexity_sum_report_int(reports, "cross_module_call_count"),
        "module_side_effect_domain_count": _complexity_sum_report_int(reports, "module_side_effect_domain_count"),
        "concurrency_module_count": _complexity_sum_report_int(reports, "concurrency_module_count"),
        "max_parameter_count": max((int(report.get("max_parameter_count", 0)) for report in reports), default=0),
        "max_local_variable_count": _complexity_max_report_int(reports, "max_local_variable_count"),
        "max_exit_point_count": _complexity_max_report_int(reports, "max_exit_point_count"),
        "side_effect_function_count": _complexity_sum_report_int(reports, "side_effect_function_count"),
        "concurrency_touchpoint_count": _complexity_sum_report_int(reports, "concurrency_touchpoint_count"),
        "module_public_api_count": _complexity_sum_report_int(reports, "module_public_api_count"),
        "module_declared_public_api_count": _complexity_sum_report_int(reports, "module_declared_public_api_count"),
        "module_public_parameter_count": _complexity_sum_report_int(reports, "module_public_parameter_count"),
        "module_max_public_parameter_count": _complexity_max_report_int(reports, "module_max_public_parameter_count"),
        "module_leaked_public_name_count": _complexity_sum_report_int(reports, "module_leaked_public_name_count"),
        "module_missing_declared_api_count": _complexity_sum_report_int(reports, "module_missing_declared_api_count"),
        "module_api_boundary_violation_count": api_boundary_violation_count,
        "module_public_value_count": _complexity_sum_report_int(reports, "module_public_value_count"),
        "module_visible_value_count": _complexity_sum_report_int(reports, "module_visible_value_count"),
        "module_leaked_public_value_count": _complexity_sum_report_int(reports, "module_leaked_public_value_count"),
        "module_declared_public_api_module_count": _complexity_count_declared_api_modules(reports),
        "module_public_side_effect_api_count": _complexity_sum_report_int(reports, "module_public_side_effect_api_count"),
        "module_public_concurrency_api_count": _complexity_sum_report_int(reports, "module_public_concurrency_api_count"),
        "module_mutable_global_count": _complexity_sum_report_int(reports, "module_mutable_global_count"),
        "complexity_levels": complexity_levels,
        "architecture_findings": architecture_findings,
        "duplication_findings": duplication_findings,
        "module_interface_findings": module_interface_findings,
        "module_boundary_findings": module_boundary_findings,
        "module_api_boundary_findings": api_boundary_findings,
        "module_api_boundary_violations": api_boundary_report.get("module_api_boundary_violations", []),
        "limit": limit,
        "top_files": top_reports,
        **_product_scope_report_fields(scope_selection),
    }
    if full:
        result["files"] = reports
    return result




def _complexity_ledger_root_for_path(path: Path) -> Path:
    resolved = path.resolve()
    return resolved if resolved.is_dir() else resolved.parent



def _complexity_trend_log_path(root: Path) -> Path:
    return root / ".centaur" / "complexity_trend.ndjson"


def _read_complexity_trend_records(root: Path, limit: int = 0) -> list[dict[str, Any]]:
    return _read_ndjson_records_with_format(_complexity_trend_log_path(root), _COMPLEXITY_TREND_FORMAT, "complexity trend", limit=limit)


def _latest_complexity_trend_hash(root: Path) -> Optional[str]:
    records = _read_complexity_trend_records(root, limit=1)
    if not records:
        return None
    value = records[-1].get("record_hash")
    return str(value) if isinstance(value, str) and value else None


def compact_complexity_scan(scan: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "format",
        "status",
        "version",
        "profile_id",
        "direction",
        "path",
        "file_count",
        "score",
        "components",
        "max_function_lines",
        "functions_over_50",
        "functions_over_100",
        "repeated_normalized_blocks",
        "total_line_count",
        "max_file_lines",
        "largest_file_line_share",
        "files_over_1000_lines",
        "files_over_3000_lines",
        "files_over_10000_lines",
        "max_file_function_count",
        "files_over_250_functions",
        "module_candidate_count",
        "max_module_candidate_function_count",
        "min_module_candidate_api_ratio",
        "project_module_complexity_score",
        "cross_module_call_count",
        "module_side_effect_domain_count",
        "concurrency_module_count",
        "max_parameter_count",
        "max_local_variable_count",
        "max_exit_point_count",
        "side_effect_function_count",
        "concurrency_touchpoint_count",
        "module_public_api_count",
        "module_declared_public_api_count",
        "module_public_parameter_count",
        "module_max_public_parameter_count",
        "module_leaked_public_name_count",
        "module_missing_declared_api_count",
        "module_api_boundary_violation_count",
        "module_public_value_count",
        "module_visible_value_count",
        "module_leaked_public_value_count",
        "module_declared_public_api_module_count",
        "module_public_side_effect_api_count",
        "module_public_concurrency_api_count",
        "module_mutable_global_count",
        "complexity_levels",
        "architecture_findings",
        "duplication_findings",
        "module_interface_findings",
        "module_boundary_findings",
        "module_api_boundary_findings",
        "module_api_boundary_violations",
        "limit",
        "top_files",
        "product_scope_mode",
        "included_file_count",
        "excluded_file_count",
        "excluded_path_samples",
        "excluded_paths_truncated",
        "artifact_dir_exclusions",
    )
    return {key: json.loads(json.dumps(scan.get(key), sort_keys=True)) for key in keys if key in scan}


def append_complexity_trend_record(
    path: Path,
    label: Optional[str] = None,
    limit: int = 25,
    full: bool = False,
    ledger_root: Optional[Path] = None,
    product_scope: str = "all",
    include_patterns: Optional[list[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
) -> dict[str, Any]:
    scan = scan_complexity(path, limit=limit, full=full, product_scope=product_scope, include_patterns=include_patterns, exclude_patterns=exclude_patterns)
    root = (ledger_root or _complexity_ledger_root_for_path(path)).resolve()
    record: dict[str, Any] = {
        "format": _COMPLEXITY_TREND_FORMAT,
        "version": 1,
        "record_id": "complexity-" + uuid.uuid4().hex,
        "profile_id": scan.get("profile_id"),
        "direction": scan.get("direction"),
        "label": label,
        "scan_path": scan.get("path"),
        "score": scan.get("score"),
        "components": scan.get("components", {}),
        "file_count": scan.get("file_count", 0),
        "max_function_lines": scan.get("max_function_lines", 0),
        "functions_over_50": scan.get("functions_over_50", 0),
        "functions_over_100": scan.get("functions_over_100", 0),
        "repeated_normalized_blocks": scan.get("repeated_normalized_blocks", 0),
        "total_line_count": scan.get("total_line_count", 0),
        "max_file_lines": scan.get("max_file_lines", 0),
        "largest_file_line_share": scan.get("largest_file_line_share", 0.0),
        "files_over_1000_lines": scan.get("files_over_1000_lines", 0),
        "files_over_3000_lines": scan.get("files_over_3000_lines", 0),
        "files_over_10000_lines": scan.get("files_over_10000_lines", 0),
        "max_file_function_count": scan.get("max_file_function_count", 0),
        "files_over_250_functions": scan.get("files_over_250_functions", 0),
        "module_candidate_count": scan.get("module_candidate_count", 0),
        "max_module_candidate_function_count": scan.get("max_module_candidate_function_count", 0),
        "min_module_candidate_api_ratio": scan.get("min_module_candidate_api_ratio", 1.0),
        "project_module_complexity_score": scan.get("project_module_complexity_score", 0.0),
        "cross_module_call_count": scan.get("cross_module_call_count", 0),
        "module_side_effect_domain_count": scan.get("module_side_effect_domain_count", 0),
        "concurrency_module_count": scan.get("concurrency_module_count", 0),
        "max_parameter_count": scan.get("max_parameter_count", 0),
        "max_local_variable_count": scan.get("max_local_variable_count", 0),
        "max_exit_point_count": scan.get("max_exit_point_count", 0),
        "side_effect_function_count": scan.get("side_effect_function_count", 0),
        "concurrency_touchpoint_count": scan.get("concurrency_touchpoint_count", 0),
        "module_public_api_count": scan.get("module_public_api_count", 0),
        "module_declared_public_api_count": scan.get("module_declared_public_api_count", 0),
        "module_leaked_public_name_count": scan.get("module_leaked_public_name_count", 0),
        "module_missing_declared_api_count": scan.get("module_missing_declared_api_count", 0),
        "module_api_boundary_violation_count": scan.get("module_api_boundary_violation_count", 0),
        "module_public_parameter_count": scan.get("module_public_parameter_count", 0),
        "module_max_public_parameter_count": scan.get("module_max_public_parameter_count", 0),
        "scan": compact_complexity_scan(scan),
        "previous_record_hash": _latest_complexity_trend_hash(root),
        "created_unix_us": _hyor_now_us(),
    }
    record["record_hash"] = _sha256_bytes(_canonical_json_bytes({key: value for key, value in record.items() if key != "record_hash"}))
    _append_ndjson_record(_complexity_trend_log_path(root), record)
    return record | {"status": "success", "path": str(_complexity_trend_log_path(root))}


def _complexity_metric_delta(latest: Optional[dict[str, Any]], previous: Optional[dict[str, Any]], key: str) -> Optional[float]:
    if not isinstance(latest, dict) or not isinstance(previous, dict):
        return None
    latest_value = latest.get(key)
    previous_value = previous.get(key)
    if not isinstance(latest_value, (int, float)) or not isinstance(previous_value, (int, float)):
        return None
    return round(float(latest_value) - float(previous_value), 6)


def _complexity_trend_direction(delta: Optional[float]) -> str:
    if delta is None:
        return "insufficient_data"
    if delta < 0:
        return "improved"
    if delta > 0:
        return "regressed"
    return "unchanged"


def summarize_complexity_trend(root: Path, limit: int = 25, full: bool = False) -> dict[str, Any]:
    records = _read_complexity_trend_records(root, limit=0)
    selected = records[-limit:] if limit > 0 else list(records)
    latest = selected[-1] if selected else None
    previous = selected[-2] if len(selected) >= 2 else None
    baseline = selected[0] if selected else None
    score_delta = _complexity_metric_delta(latest, previous, "score")
    baseline_delta = _complexity_metric_delta(latest, baseline, "score") if latest is not baseline else 0.0 if latest else None
    best = None
    if selected:
        best = min(selected, key=lambda item: float(item.get("score", 0.0) if isinstance(item.get("score"), (int, float)) else math.inf))
    result: dict[str, Any] = {
        "format": _COMPLEXITY_TREND_FORMAT,
        "status": "success",
        "version": 1,
        "direction": "lower_is_better",
        "record_count": len(records),
        "returned_count": len(selected),
        "path": str(_complexity_trend_log_path(root)),
        "latest": latest,
        "previous_score_delta": score_delta,
        "baseline_score_delta": baseline_delta,
        "trend": _complexity_trend_direction(score_delta),
        "max_function_lines_delta": _complexity_metric_delta(latest, previous, "max_function_lines"),
        "functions_over_50_delta": _complexity_metric_delta(latest, previous, "functions_over_50"),
        "functions_over_100_delta": _complexity_metric_delta(latest, previous, "functions_over_100"),
        "repeated_normalized_blocks_delta": _complexity_metric_delta(latest, previous, "repeated_normalized_blocks"),
        "max_file_lines_delta": _complexity_metric_delta(latest, previous, "max_file_lines"),
        "max_file_function_count_delta": _complexity_metric_delta(latest, previous, "max_file_function_count"),
        "files_over_10000_lines_delta": _complexity_metric_delta(latest, previous, "files_over_10000_lines"),
        "module_candidate_count_delta": _complexity_metric_delta(latest, previous, "module_candidate_count"),
        "max_module_candidate_function_count_delta": _complexity_metric_delta(latest, previous, "max_module_candidate_function_count"),
        "project_module_complexity_score_delta": _complexity_metric_delta(latest, previous, "project_module_complexity_score"),
        "cross_module_call_count_delta": _complexity_metric_delta(latest, previous, "cross_module_call_count"),
        "module_public_api_count_delta": _complexity_metric_delta(latest, previous, "module_public_api_count"),
        "module_declared_public_api_count_delta": _complexity_metric_delta(latest, previous, "module_declared_public_api_count"),
        "module_leaked_public_name_count_delta": _complexity_metric_delta(latest, previous, "module_leaked_public_name_count"),
        "module_missing_declared_api_count_delta": _complexity_metric_delta(latest, previous, "module_missing_declared_api_count"),
        "module_api_boundary_violation_count_delta": _complexity_metric_delta(latest, previous, "module_api_boundary_violation_count"),
        "module_public_parameter_count_delta": _complexity_metric_delta(latest, previous, "module_public_parameter_count"),
        "module_max_public_parameter_count_delta": _complexity_metric_delta(latest, previous, "module_max_public_parameter_count"),
        "concurrency_module_count_delta": _complexity_metric_delta(latest, previous, "concurrency_module_count"),
        "max_parameter_count_delta": _complexity_metric_delta(latest, previous, "max_parameter_count"),
        "max_local_variable_count_delta": _complexity_metric_delta(latest, previous, "max_local_variable_count"),
        "best": None if best is None else {
            "record_id": best.get("record_id"),
            "record_hash": best.get("record_hash"),
            "label": best.get("label"),
            "score": best.get("score"),
            "created_unix_us": best.get("created_unix_us"),
        },
    }
    if full:
        result["records"] = selected
    return result



def _complexity_gate_metric_value(source: Optional[dict[str, Any]], key: str) -> Optional[float]:
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def _complexity_gate_thresholds(
    max_score_increase: float,
    max_max_function_lines_increase: int,
    max_functions_over_50_increase: int,
    max_functions_over_100_increase: int,
    max_repeated_blocks_increase: int,
    max_file_lines_increase: int,
    max_file_functions_increase: int,
) -> dict[str, float]:
    return {
        "score": float(max_score_increase),
        "max_function_lines": float(max_max_function_lines_increase),
        "functions_over_50": float(max_functions_over_50_increase),
        "functions_over_100": float(max_functions_over_100_increase),
        "repeated_normalized_blocks": float(max_repeated_blocks_increase),
        "max_file_lines": float(max_file_lines_increase),
        "max_file_function_count": float(max_file_functions_increase),
    }


def _build_complexity_gate_check(current: dict[str, Any], baseline: dict[str, Any], name: str, max_growth: float) -> dict[str, Any]:
    current_value = _complexity_gate_metric_value(current, name)
    baseline_value = _complexity_gate_metric_value(baseline, name)
    if current_value is None or baseline_value is None:
        return {"name": name, "ok": False, "reason": "missing_metric", "max_growth": float(max_growth)}
    delta = round(current_value - baseline_value, 6)
    return {
        "name": name,
        "ok": delta <= float(max_growth),
        "current": current_value,
        "baseline": baseline_value,
        "delta": delta,
        "max_growth": float(max_growth),
    }


def _latest_complexity_gate_baseline(root: Path) -> Optional[dict[str, Any]]:
    records = _read_complexity_trend_records(root, limit=1)
    return records[-1] if records else None


def _complexity_gate_baseline_scan(record: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(record, dict):
        return None
    scan = record.get("scan")
    return scan if isinstance(scan, dict) else record


def evaluate_complexity_gate(
    path: Path,
    ledger_root: Optional[Path] = None,
    label: Optional[str] = None,
    limit: int = 25,
    full: bool = False,
    max_score_increase: float = _DEFAULT_COMPLEXITY_GATE_MAX_SCORE_INCREASE,
    max_max_function_lines_increase: int = _DEFAULT_COMPLEXITY_GATE_MAX_MAX_FUNCTION_LINES_INCREASE,
    max_functions_over_50_increase: int = _DEFAULT_COMPLEXITY_GATE_MAX_FUNCTIONS_OVER_50_INCREASE,
    max_functions_over_100_increase: int = _DEFAULT_COMPLEXITY_GATE_MAX_FUNCTIONS_OVER_100_INCREASE,
    max_repeated_blocks_increase: int = _DEFAULT_COMPLEXITY_GATE_MAX_REPEATED_BLOCKS_INCREASE,
    max_file_lines_increase: int = _DEFAULT_COMPLEXITY_GATE_MAX_FILE_LINES_INCREASE,
    max_file_functions_increase: int = _DEFAULT_COMPLEXITY_GATE_MAX_FILE_FUNCTIONS_INCREASE,
    allow_no_baseline: bool = False,
    record: bool = False,
    product_scope: str = "all",
    include_patterns: Optional[list[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
) -> dict[str, Any]:
    if limit < 0:
        raise ComplexityError("limit must be >= 0")
    scan = scan_complexity(path, limit=limit, full=full, product_scope=product_scope, include_patterns=include_patterns, exclude_patterns=exclude_patterns)
    root = (ledger_root or _complexity_ledger_root_for_path(path)).resolve()
    baseline_record = _latest_complexity_gate_baseline(root)
    baseline = _complexity_gate_baseline_scan(baseline_record)
    thresholds = _complexity_gate_thresholds(max_score_increase, max_max_function_lines_increase, max_functions_over_50_increase, max_functions_over_100_increase, max_repeated_blocks_increase, max_file_lines_increase, max_file_functions_increase)
    checks = [] if baseline is None else [_build_complexity_gate_check(scan, baseline, name, growth) for name, growth in thresholds.items()]
    violations = [check for check in checks if not bool(check.get("ok"))]
    gate_satisfied = (baseline is None and allow_no_baseline) or (baseline is not None and not violations)
    decision = "accept" if gate_satisfied else "missing_baseline" if baseline is None else "reject"
    verdict = "accepted" if gate_satisfied else "missing_baseline" if baseline is None else "rejected"
    reason = "ok" if gate_satisfied else "no_complexity_baseline" if baseline is None else "complexity_regression"
    result: dict[str, Any] = {
        "format": _COMPLEXITY_GATE_FORMAT,
        "status": "success",
        "version": 1,
        "profile_id": scan.get("profile_id"),
        "direction": "lower_is_better",
        "path": scan.get("path"),
        "ledger_root": str(root),
        "decision": decision,
        "verdict": verdict,
        "reason": reason,
        "gate_satisfied": gate_satisfied,
        "thresholds": thresholds,
        "checks": checks,
        "violation_count": len(violations),
        "violations": violations,
        "current": compact_complexity_scan(scan),
        "baseline": compact_complexity_scan(baseline) if isinstance(baseline, dict) else None,
    }
    if baseline_record is not None:
        result["baseline_record_id"] = baseline_record.get("record_id")
        result["baseline_record_hash"] = baseline_record.get("record_hash")
    if record:
        recorded = append_complexity_trend_record(path, label=label or f"gate:{decision}", limit=limit, full=full, ledger_root=root, product_scope=product_scope, include_patterns=include_patterns, exclude_patterns=exclude_patterns)
        result["recorded"] = recorded
        result["record"] = recorded
    return result


def complexity_drilldown(path: Path, file_limit: int = 25, function_limit: int = 25, full: bool = False) -> dict[str, Any]:
    scan = scan_complexity(path, limit=0, full=True)
    reports = scan.get("files", []) if isinstance(scan.get("files"), list) else []
    file_rows: list[dict[str, Any]] = []
    function_rows: list[dict[str, Any]] = []
    repeated_rows: list[dict[str, Any]] = []
    module_rows: list[dict[str, Any]] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        file_rows.append({
            "relative_path": report.get("relative_path"),
            "score": report.get("score"),
            "components": report.get("components", {}),
            "max_function_lines": report.get("max_function_lines"),
            "functions_over_50": report.get("functions_over_50"),
            "functions_over_100": report.get("functions_over_100"),
            "repeated_normalized_blocks": report.get("repeated_normalized_blocks"),
            "file_architecture_score": report.get("file_architecture_score"),
            "architecture_flags": report.get("architecture_flags"),
            "line_count": report.get("line_count"),
            "function_count": report.get("function_count"),
            "top_level_definition_count": report.get("top_level_definition_count"),
            "module_interface_score": report.get("module_interface_score"),
            "module_public_api_count": report.get("module_public_api_count"),
            "module_declared_public_api_count": report.get("module_declared_public_api_count"),
            "module_leaked_public_name_count": report.get("module_leaked_public_name_count"),
            "module_missing_declared_api_count": report.get("module_missing_declared_api_count"),
            "module_public_value_count": report.get("module_public_value_count"),
            "module_visible_value_count": report.get("module_visible_value_count"),
            "module_leaked_public_value_count": report.get("module_leaked_public_value_count"),
            "module_uses_declared_public_api": report.get("module_uses_declared_public_api"),
            "module_public_side_effect_api_count": report.get("module_public_side_effect_api_count"),
            "module_public_concurrency_api_count": report.get("module_public_concurrency_api_count"),
            "module_mutable_global_count": report.get("module_mutable_global_count"),
            "module_interface_flags": report.get("module_interface_flags"),
            "module_boundary_score": report.get("module_boundary_score"),
            "module_candidate_count": report.get("module_candidate_count"),
            "max_module_candidate_function_count": report.get("max_module_candidate_function_count"),
            "min_module_candidate_api_ratio": report.get("min_module_candidate_api_ratio"),
            "project_module_complexity_score": report.get("project_module_complexity_score"),
            "cross_module_call_count": report.get("cross_module_call_count"),
            "module_side_effect_domain_count": report.get("module_side_effect_domain_count"),
            "concurrency_module_count": report.get("concurrency_module_count"),
            "function_state_score": report.get("function_state_score"),
            "max_parameter_count": report.get("max_parameter_count"),
            "max_local_variable_count": report.get("max_local_variable_count"),
            "max_exit_point_count": report.get("max_exit_point_count"),
            "lines_over_100": report.get("lines_over_100"),
            "lines_over_140": report.get("lines_over_140"),
        })
        if int(report.get("repeated_normalized_blocks", 0) or 0) > 0:
            repeated_rows.append({
                "relative_path": report.get("relative_path"),
                "repeated_normalized_blocks": report.get("repeated_normalized_blocks"),
                "repeated_block_byte_estimate": report.get("repeated_block_byte_estimate"),
                "duplication_score": report.get("components", {}).get("duplication") if isinstance(report.get("components"), dict) else None,
            })
        for candidate in report.get("module_boundary_candidates", []) if isinstance(report.get("module_boundary_candidates"), list) else []:
            if not isinstance(candidate, dict):
                continue
            module_rows.append(dict(candidate))
        for function_record in report.get("largest_functions", []) if isinstance(report.get("largest_functions"), list) else []:
            if not isinstance(function_record, dict):
                continue
            row = dict(function_record)
            row["relative_path"] = report.get("relative_path")
            function_rows.append(row)
    file_rows.sort(key=lambda item: (-float(item.get("score", 0.0) or 0.0), str(item.get("relative_path", ""))))
    function_rows.sort(key=lambda item: (-int(item.get("line_count", 0) or 0), -int(item.get("cyclomatic", 0) or 0), -int(item.get("nesting_depth", 0) or 0), str(item.get("relative_path", "")), str(item.get("name", ""))))
    repeated_rows.sort(key=lambda item: (-int(item.get("repeated_normalized_blocks", 0) or 0), str(item.get("relative_path", ""))))
    module_rows.sort(key=lambda item: (-float(item.get("boundary_pressure", 0.0) or 0.0), str(item.get("relative_path", "")), str(item.get("module_key", ""))))
    architecture_rows = [row for row in file_rows if float(row.get("file_architecture_score", 0.0) or 0.0) > 0.0]
    architecture_rows.sort(key=lambda item: (-float(item.get("file_architecture_score", 0.0) or 0.0), -int(item.get("line_count", 0) or 0), str(item.get("relative_path", ""))))
    interface_rows = [row for row in file_rows if float(row.get("module_interface_score", 0.0) or 0.0) > 0.0]
    interface_rows.sort(key=lambda item: (-float(item.get("module_interface_score", 0.0) or 0.0), -int(item.get("module_public_api_count", 0) or 0), str(item.get("relative_path", ""))))
    summary = {key: scan.get(key) for key in ("format", "status", "version", "profile_id", "direction", "path", "file_count", "score", "components", "max_function_lines", "functions_over_50", "functions_over_100", "repeated_normalized_blocks", "max_file_lines", "max_file_function_count", "files_over_10000_lines", "module_candidate_count", "max_module_candidate_function_count", "min_module_candidate_api_ratio", "project_module_complexity_score", "cross_module_call_count", "module_side_effect_domain_count", "concurrency_module_count", "max_parameter_count", "max_local_variable_count", "max_exit_point_count", "side_effect_function_count", "concurrency_touchpoint_count", "module_public_api_count", "module_declared_public_api_count", "module_leaked_public_name_count", "module_declared_public_api_module_count", "module_public_side_effect_api_count", "module_public_concurrency_api_count", "module_mutable_global_count", "complexity_levels")}
    result: dict[str, Any] = {
        "format": _COMPLEXITY_DRILLDOWN_FORMAT,
        "status": "success",
        "version": 1,
        "summary": summary,
        "top_files": file_rows if file_limit == 0 else file_rows[:file_limit],
        "largest_functions": function_rows if function_limit == 0 else function_rows[:function_limit],
        "repeated_block_files": repeated_rows if file_limit == 0 else repeated_rows[:file_limit],
        "architecture_hotspots": architecture_rows if file_limit == 0 else architecture_rows[:file_limit],
        "module_interface_hotspots": interface_rows if file_limit == 0 else interface_rows[:file_limit],
        "module_boundary_hotspots": module_rows if file_limit == 0 else module_rows[:file_limit],
    }
    if full:
        result["scan"] = scan
    return result



def _complexity_sanitize_module_name_piece(value: str) -> str:
    return _sanitize_module_name_piece(value)


def _complexity_suggested_module_name(relative_path: str, module_key: str) -> str:
    source_path = Path(relative_path)
    stem = _complexity_sanitize_module_name_piece(source_path.stem)
    key = _complexity_sanitize_module_name_piece(module_key)
    if key == stem:
        return f"{stem}_module.py"
    return f"{stem}_{key}.py"


def _complexity_trim_module_candidate(candidate: dict[str, Any], full: bool) -> dict[str, Any]:
    result = dict(candidate)
    result["suggested_module"] = _complexity_suggested_module_name(str(candidate.get("relative_path", "source.py")), str(candidate.get("module_key", "module")))
    result["preserved_public_api"] = list(candidate.get("api_function_names", []))[:50]
    if not full:
        result["api_function_names"] = list(candidate.get("api_function_names", []))[:12]
        result["representative_function_names"] = list(candidate.get("representative_function_names", []))[:12]
    side_effects = result.get("side_effect_domains") if isinstance(result.get("side_effect_domains"), list) else []
    concurrency_count = int(result.get("concurrency_touchpoint_count", 0) or 0)
    result["migration_kind"] = "capability_module_with_facade"
    result["state_isolation_benefit"] = "contains concurrency behind the preserved API" if concurrency_count else "contains side effects behind the preserved API" if side_effects else "contains helper state behind the preserved API"
    result["acceptance_gate"] = "roundtrip, targeted tests, complexity gate, and unchanged public API names"
    return result


def _collect_complexity_module_plan_candidates(scan: dict[str, Any], min_functions: int, max_api_ratio: float, full: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    reports = scan.get("files", []) if isinstance(scan.get("files"), list) else []
    for report in reports:
        candidates = report.get("module_boundary_candidates") if isinstance(report, dict) else []
        if not isinstance(candidates, list):
            continue
        already_declared_api_module = bool(report.get("module_uses_declared_public_api")) and int(report.get("module_leaked_public_name_count", 0) or 0) == 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            function_count = int(candidate.get("function_count", 0) or 0)
            api_ratio = float(candidate.get("api_to_function_ratio", 1.0) or 1.0)
            row = _complexity_trim_module_candidate(candidate, full)
            if already_declared_api_module:
                row["defer_reason"] = "already_declared_api_module"
                deferred.append(row)
            elif function_count >= min_functions and api_ratio <= max_api_ratio:
                selected.append(row)
            elif function_count >= min_functions:
                row["defer_reason"] = "api_surface_too_large_for_safe_first_extraction"
                deferred.append(row)
    selected.sort(key=lambda item: (-float(item.get("boundary_pressure", 0.0)), str(item.get("suggested_module", ""))))
    deferred.sort(key=lambda item: (-float(item.get("boundary_pressure", 0.0)), str(item.get("suggested_module", ""))))
    return selected, deferred


def build_complexity_module_plan(path: Path, limit: int = 25, min_functions: int = 6, max_api_ratio: float = 0.70, full: bool = False) -> dict[str, Any]:
    if limit < 0:
        raise ComplexityError("limit must be >= 0")
    if min_functions < 1:
        raise ComplexityError("min_functions must be >= 1")
    if max_api_ratio < 0.0 or max_api_ratio > 1.0:
        raise ComplexityError("max_api_ratio must be between 0 and 1")
    scan = scan_complexity(path, limit=0, full=True)
    selected, deferred = _collect_complexity_module_plan_candidates(scan, min_functions, max_api_ratio, full)
    limited_selected = selected if limit == 0 else selected[:limit]
    limited_deferred = deferred if limit == 0 else deferred[:limit]
    return {
        "format": _COMPLEXITY_MODULE_PLAN_FORMAT,
        "status": "success",
        "version": 1,
        "profile_id": scan.get("profile_id"),
        "path": scan.get("path"),
        "policy": "Prefer cohesive capability modules with small preserved APIs; never split files only by line count.",
        "min_functions": min_functions,
        "max_api_ratio": max_api_ratio,
        "candidate_count": len(selected),
        "deferred_candidate_count": len(deferred),
        "candidates": limited_selected,
        "deferred_candidates": limited_deferred,
        "migration_steps": [
            "choose one candidate with a low api_to_function_ratio and clear module_key",
            "move helper functions behind the listed preserved_public_api",
            "leave a thin compatibility facade until callers are migrated",
            "run targeted impact tests, roundtrip/selftest, and complexity-gate before accepting",
            "reject the extraction if the new module raises total module complexity more than it lowers boundary pressure",
            "only then repeat for the next independent capability cluster",
        ],
        "summary": compact_complexity_scan(scan),
    }

def _parse_complexity_calibration_example(root: Path, spec: str) -> dict[str, Any]:
    if "=" not in spec:
        raise ComplexityError("complexity calibration examples must use LABEL=PATH")
    label, raw_path = spec.split("=", 1)
    label = label.strip().lower()
    raw_path = raw_path.strip()
    if not label:
        raise ComplexityError("complexity calibration label cannot be empty")
    if not raw_path:
        raise ComplexityError("complexity calibration path cannot be empty")
    target = Path(raw_path)
    if not target.is_absolute():
        target = root / target
    return {"label": label, "path": target}


def _average_complexity_component(rows: list[dict[str, Any]], component_name: str) -> float:
    if not rows:
        return 0.0
    return round(sum(float(row.get("components", {}).get(component_name, 0.0)) for row in rows) / len(rows), 6)


def _average_complexity_score(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return round(sum(float(row.get("score", 0.0)) for row in rows) / len(rows), 6)


def _select_complexity_calibration_label(grouped: dict[str, list[dict[str, Any]]], preferred: tuple[str, ...], reverse_score: bool = False) -> Optional[str]:
    for label in preferred:
        if label in grouped:
            return label
    if not grouped:
        return None
    ordered = sorted(grouped.items(), key=lambda item: _average_complexity_score(item[1]), reverse=reverse_score)
    return ordered[0][0]


def _recommended_complexity_component_weights(component_separation: dict[str, float]) -> dict[str, float]:
    positive_values = [value for value in component_separation.values() if value > 0]
    baseline = sum(positive_values) / len(positive_values) if positive_values else 1.0
    weights: dict[str, float] = {}
    for name in _COMPLEXITY_COMPONENT_NAMES:
        separation = float(component_separation.get(name, 0.0))
        if separation <= 0:
            weights[name] = 0.5
        else:
            weights[name] = round(max(0.25, min(4.0, separation / baseline)), 3)
    return weights


def _complexity_calibration_pairwise_accuracy(clean_rows: list[dict[str, Any]], gnarly_rows: list[dict[str, Any]]) -> float:
    total = 0
    correct = 0
    for clean_row in clean_rows:
        for gnarly_row in gnarly_rows:
            total += 1
            if float(clean_row.get("score", 0.0)) < float(gnarly_row.get("score", 0.0)):
                correct += 1
    return round(correct / total, 6) if total else 0.0


def calibrate_complexity_metric(root: Path, example_specs: list[str], limit: int = 5, full: bool = False) -> dict[str, Any]:
    if not example_specs:
        raise ComplexityError("at least one --example LABEL=PATH is required")
    examples: list[dict[str, Any]] = []
    for spec in example_specs:
        parsed = _parse_complexity_calibration_example(root, spec)
        scan = scan_complexity(Path(parsed["path"]), limit=limit, full=full)
        examples.append({"label": parsed["label"], "path": str(Path(parsed["path"]).resolve()), "score": scan.get("score"), "components": scan.get("components", {}), "scan": scan if full else compact_complexity_scan(scan)})
    grouped: dict[str, list[dict[str, Any]]] = {}
    for example in examples:
        grouped.setdefault(str(example["label"]), []).append(example)
    group_summaries: dict[str, dict[str, Any]] = {}
    for label, rows in sorted(grouped.items()):
        group_summaries[label] = {
            "count": len(rows),
            "average_score": _average_complexity_score(rows),
            "average_components": {name: _average_complexity_component(rows, name) for name in _COMPLEXITY_COMPONENT_NAMES},
        }
    clean_label = _select_complexity_calibration_label(grouped, ("clean", "simple", "good"), reverse_score=False)
    gnarly_label = _select_complexity_calibration_label(grouped, ("gnarly", "complex", "bad"), reverse_score=True)
    component_separation = {name: 0.0 for name in _COMPLEXITY_COMPONENT_NAMES}
    score_separation = 0.0
    pairwise_accuracy = 0.0
    if clean_label and gnarly_label and clean_label != gnarly_label:
        clean_rows = grouped[clean_label]
        gnarly_rows = grouped[gnarly_label]
        score_separation = round(_average_complexity_score(gnarly_rows) - _average_complexity_score(clean_rows), 6)
        component_separation = {name: round(_average_complexity_component(gnarly_rows, name) - _average_complexity_component(clean_rows, name), 6) for name in _COMPLEXITY_COMPONENT_NAMES}
        pairwise_accuracy = _complexity_calibration_pairwise_accuracy(clean_rows, gnarly_rows)
    return {
        "format": _COMPLEXITY_CALIBRATION_FORMAT,
        "status": "success",
        "version": 1,
        "profile_id": _DEFAULT_COMPLEXITY_PROFILE_ID,
        "direction": "lower_is_better",
        "root": str(root.resolve()),
        "example_count": len(examples),
        "labels": sorted(grouped),
        "group_summaries": group_summaries,
        "reference_labels": {"clean": clean_label, "gnarly": gnarly_label},
        "score_separation": score_separation,
        "component_separation": component_separation,
        "pairwise_accuracy": pairwise_accuracy,
        "recommended_component_weights": _recommended_complexity_component_weights(component_separation),
        "examples": examples if full else [{key: value for key, value in example.items() if key != "scan"} for example in examples],
    }


def scan_complexity_or_missing(path: Path, limit: int = 25, full: bool = False) -> dict[str, Any]:
    if not path.exists():
        return {
            "format": _COMPLEXITY_SCAN_FORMAT,
            "status": "missing",
            "version": 1,
            "profile_id": _DEFAULT_COMPLEXITY_PROFILE_ID,
            "direction": "lower_is_better",
            "path": str(path),
            "file_count": 0,
            "score": 0.0,
            "components": {name: 0.0 for name in _COMPLEXITY_COMPONENT_NAMES},
            "max_function_lines": 0,
            "functions_over_50": 0,
            "functions_over_100": 0,
            "repeated_normalized_blocks": 0,
            "module_candidate_count": 0,
            "max_module_candidate_function_count": 0,
            "min_module_candidate_api_ratio": 1.0,
            "module_declared_public_api_count": 0,
            "module_leaked_public_name_count": 0,
            "module_missing_declared_api_count": 0,
            "module_public_parameter_count": 0,
            "module_max_public_parameter_count": 0,
            "module_public_value_count": 0,
            "module_visible_value_count": 0,
            "module_leaked_public_value_count": 0,
            "module_declared_public_api_module_count": 0,
            "module_boundary_findings": [],
            "limit": limit,
            "top_files": [],
        }
    return scan_complexity(path, limit=limit, full=full)
