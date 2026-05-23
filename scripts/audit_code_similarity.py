#!/usr/bin/env python3
"""Similarity-aware DRY audit for scripts/.

This adapter intentionally imports Centaur's DRY similarity scorer instead of
reimplementing it here. It only adapts Python function bodies into Centaur
piece records.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any


DEFAULT_SIMILARITY_THRESHOLD = 0.85
DEFAULT_MIN_FUNCTION_LINES = 40
DEFAULT_SHINGLE_WIDTH = 5
DEFAULT_PREFILTER_FLOOR = DEFAULT_SIMILARITY_THRESHOLD


@dataclass(frozen=True)
class FunctionPiece:
    path: pathlib.Path
    qualname: str
    source: str
    line_count: int
    rel_id: str


def _candidate_centaur_roots(repo: pathlib.Path, explicit: str | None) -> list[pathlib.Path]:
    candidates: list[pathlib.Path] = []
    if explicit:
        candidates.append(pathlib.Path(explicit).expanduser())
    if os.environ.get("CENTAUR_REPO"):
        candidates.append(pathlib.Path(str(os.environ["CENTAUR_REPO"])).expanduser())
    candidates.extend(
        [
            repo.parent / "centaur",
            pathlib.Path("/private/tmp/centaur-track1-1258"),
            pathlib.Path("/private/tmp/centaur-main-clean-pydeps"),
        ]
    )
    return candidates


def resolve_centaur_root(repo: pathlib.Path, explicit: str | None) -> pathlib.Path:
    for candidate in _candidate_centaur_roots(repo, explicit):
        if (candidate / "centaur.py").is_file():
            return candidate.resolve()
    raise RuntimeError("Centaur repo not found; set CENTAUR_REPO or pass --centaur-root")


def add_centaur_dependency_paths() -> None:
    candidates = []
    if os.environ.get("CENTAUR_PYDEPS"):
        candidates.append(pathlib.Path(str(os.environ["CENTAUR_PYDEPS"])).expanduser())
    candidates.append(pathlib.Path("/private/tmp/centaur-main-clean-pydeps"))
    for candidate in candidates:
        if candidate.is_dir():
            sys.path.insert(0, str(candidate.resolve()))


def import_centaur_similarity(centaur_root: pathlib.Path) -> dict[str, Any]:
    add_centaur_dependency_paths()
    sys.path.insert(0, str(centaur_root))
    from centaur import canonicalize_for_dry as centaur_canonicalize_for_dry
    from centaur import cosine_similarity as centaur_cosine_similarity
    from centaur import dry_similarity as centaur_dry_similarity
    from centaur import jaccard_similarity as centaur_jaccard_similarity
    from centaur import normalize_text as centaur_normalize_text
    from centaur import sha256_bytes as centaur_sha256_bytes
    from centaur import shingle_tokens as centaur_shingle_tokens
    from centaur import token_counts as centaur_token_counts

    return {
        "canonicalize_for_dry": centaur_canonicalize_for_dry,
        "cosine_similarity": centaur_cosine_similarity,
        "dry_similarity": centaur_dry_similarity,
        "jaccard_similarity": centaur_jaccard_similarity,
        "normalize_text": centaur_normalize_text,
        "sha256_bytes": centaur_sha256_bytes,
        "shingle_tokens": centaur_shingle_tokens,
        "token_counts": centaur_token_counts,
    }


def _function_end_line(node: ast.AST) -> int:
    return int(getattr(node, "end_lineno", getattr(node, "lineno", 0)))


def collect_script_functions(repo: pathlib.Path, min_lines: int) -> list[FunctionPiece]:
    pieces: list[FunctionPiece] = []
    scripts_dir = repo / "scripts"
    for path in sorted(scripts_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            source = ast.get_source_segment(text, node) or ""
            line_count = max(1, (_function_end_line(node) - int(node.lineno) + 1))
            if line_count < min_lines or not source.strip():
                continue
            rel = path.relative_to(repo).as_posix()
            rel_id = f"{rel}::{node.name}@{node.lineno}"
            pieces.append(FunctionPiece(path, node.name, source, line_count, rel_id))
    return pieces


def _safe_piece_dir_name(rel_id: str) -> str:
    digest = hashlib.sha256(rel_id.encode("utf-8")).hexdigest()[:16]
    return "piece_" + digest


def _write_piece_content(root: pathlib.Path, piece: FunctionPiece) -> str:
    piece_dir = root / _safe_piece_dir_name(piece.rel_id)
    piece_dir.mkdir(parents=True, exist_ok=True)
    (piece_dir / "content").write_text(piece.source, encoding="utf-8")
    return piece_dir.name


def build_centaur_description(root: pathlib.Path, piece: FunctionPiece, helpers: dict[str, Any]) -> dict[str, Any]:
    rel_path = _write_piece_content(root, piece)
    normalized = helpers["normalize_text"](piece.source)
    canonical = helpers["canonicalize_for_dry"](piece.source)
    return {
        "format": "centaur-dry-description-v1",
        "path": rel_path,
        "kind": "leaf",
        "content_hash": helpers["sha256_bytes"](piece.source.encode("utf-8")),
        "summary": piece.rel_id,
        "behavior": {"symbol": piece.qualname, "signature": piece.source.splitlines()[0].strip(), "inputs": [], "outputs": "", "first_line": piece.source.splitlines()[0].strip()},
        "tokens": helpers["token_counts"](normalized),
        "canonical_tokens": helpers["token_counts"](canonical),
        "canonical_hash": helpers["sha256_bytes"](canonical.encode("utf-8")) if canonical else None,
        "normalized_hash": helpers["sha256_bytes"](normalized.encode("utf-8")) if normalized else None,
        "line_count": piece.line_count,
        "size_bytes": len(piece.source.encode("utf-8")),
        "source_ref": piece.rel_id,
    }


def _line_ratio(left: FunctionPiece, right: FunctionPiece) -> float:
    low = min(left.line_count, right.line_count)
    high = max(left.line_count, right.line_count)
    return 0.0 if high == 0 else low / float(high)


def _prefilter_score(left: dict[str, Any], right: dict[str, Any], helpers: dict[str, Any], shingle_width: int) -> float:
    if left.get("content_hash") == right.get("content_hash"):
        return 1.0
    if left.get("normalized_hash") == right.get("normalized_hash"):
        return 0.98
    if left.get("canonical_hash") == right.get("canonical_hash"):
        return 0.90
    left_tokens = {str(key): int(value) for key, value in (left.get("canonical_tokens") or {}).items()}
    right_tokens = {str(key): int(value) for key, value in (right.get("canonical_tokens") or {}).items()}
    token_score = helpers["cosine_similarity"](left_tokens, right_tokens)
    left_shingles = helpers["shingle_tokens"](list(left_tokens.keys()), shingle_width)
    right_shingles = helpers["shingle_tokens"](list(right_tokens.keys()), shingle_width)
    shingle_score = helpers["jaccard_similarity"](left_shingles, right_shingles)
    return max(float(token_score), float(shingle_score))


def run_similarity_audit(repo: pathlib.Path, centaur_root: pathlib.Path, threshold: float, min_lines: int, shingle_width: int, max_pairs: int, prefilter_floor: float = DEFAULT_PREFILTER_FLOOR) -> dict[str, Any]:
    started = time.time()
    helpers = import_centaur_similarity(centaur_root)
    pieces = collect_script_functions(repo, min_lines)
    pairs: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ds4-centaur-sim-") as temp_dir:
        piece_root = pathlib.Path(temp_dir)
        descriptions = [build_centaur_description(piece_root, piece, helpers) for piece in pieces]
        for left_index in range(0, len(descriptions)):
            for right_index in range(left_index + 1, len(descriptions)):
                if _line_ratio(pieces[left_index], pieces[right_index]) < 0.45:
                    continue
                if _prefilter_score(descriptions[left_index], descriptions[right_index], helpers, shingle_width) < prefilter_floor:
                    continue
                pair = helpers["dry_similarity"](piece_root, descriptions[left_index], descriptions[right_index], shingle_width)
                score = float(pair.get("score", 0.0))
                if score < threshold:
                    continue
                pair = dict(pair)
                pair["left"] = pieces[left_index].rel_id
                pair["right"] = pieces[right_index].rel_id
                pair["left_lines"] = pieces[left_index].line_count
                pair["right_lines"] = pieces[right_index].line_count
                pairs.append(pair)
    pairs.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("left", "")), str(item.get("right", ""))))
    if max_pairs > 0:
        pairs = pairs[:max_pairs]
    return {
        "format": "ds4-script-centaur-similarity-audit-v1",
        "repo": str(repo),
        "centaur_root": str(centaur_root),
        "centaur_import": "from centaur import dry_similarity as centaur_dry_similarity",
        "threshold": threshold,
        "prefilter_floor": prefilter_floor,
        "min_function_lines": min_lines,
        "shingle_width": shingle_width,
        "function_count": len(pieces),
        "pair_count": len(pairs),
        "elapsed_seconds": round(time.time() - started, 3),
        "reasons": dict(Counter(str(pair.get("reason", "")) for pair in pairs)),
        "pairs": pairs,
    }


def pair_keys(pairs: list[dict[str, Any]]) -> set[str]:
    return {str(pair.get("left", "")) + " <=> " + str(pair.get("right", "")) for pair in pairs}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(pathlib.Path(__file__).resolve().parent.parent))
    parser.add_argument("--centaur-root")
    parser.add_argument("--threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
    parser.add_argument("--min-lines", type=int, default=DEFAULT_MIN_FUNCTION_LINES)
    parser.add_argument("--shingle-width", type=int, default=DEFAULT_SHINGLE_WIDTH)
    parser.add_argument("--prefilter-floor", type=float, default=DEFAULT_PREFILTER_FLOOR)
    parser.add_argument("--max-pairs", type=int, default=200)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = pathlib.Path(args.repo).resolve()
    centaur_root = resolve_centaur_root(repo, args.centaur_root)
    result = run_similarity_audit(repo, centaur_root, args.threshold, args.min_lines, args.shingle_width, args.max_pairs, args.prefilter_floor)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Centaur similarity audit: functions={result['function_count']} pairs={result['pair_count']} threshold={result['threshold']} elapsed={result['elapsed_seconds']}s")
        print(f"Centaur import: {result['centaur_import']}")
        for pair in result["pairs"][:25]:
            print(f"{float(pair.get('score', 0.0)):.3f} {pair.get('reason')} {pair.get('left')} <=> {pair.get('right')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
