from __future__ import annotations

import base64
import hashlib
import json
import random
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ds4_infer.builders import model_batch_item
from ds4_infer.kv_cache import KV_CACHE_PLAN_FORMAT, normalize_kv_cache_directive, resolve_request_cache_refs
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import InferenceQueue, request_batch_key
from ds4_infer.runners import OpenAICompatibleRunner
from ds4_infer.schemas import InferenceRequest

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _base_request(request_id: str = "kv-r") -> dict:
    return {
        "format": "ds4-inference-request-v1",
        "request_id": request_id,
        "capability": "efficient",
        "chat": False,
        "immediate": False,
        "job_class": "summary",
        "max_output_tokens": 32,
        "thinking_budget_tokens": 0,
        "temperature": 0,
        "input": {
            "shared_prefix": "stable long memory prefix",
            "shared_prefix_hash": "sha256:prefix",
            "skeleton_hash": "sha256:prefix",
            "suffix": "question",
        },
        "output_contract": {"format": "text"},
    }


def _inline_directive(data: bytes) -> dict:
    return {
        "format": "ds4-kv-cache-directive-v1",
        "backend": "lmcache",
        "cache_id": "qwen27:longmem:case-a",
        "prefix_hash": "sha256:prefix",
        "load": {
            "mode": "require",
            "transport": "inline",
            "bytes": len(data),
            "sha256": _sha(data),
            "data_b64": base64.b64encode(data).decode("ascii"),
        },
        "store": {
            "mode": "write_back",
            "transport": "remote_uri",
            "uri": "https://cache.example/ds4/kv/case-a",
            "on_error": "warn",
        },
        "model_fingerprint": {"model": "Qwen/Qwen3.6-27B-FP8", "tp": 1},
    }


class CapturingRunner(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.payloads: list[dict] = []

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"choices": [{"text": "ok"}]}


class KvCacheApiTests(unittest.TestCase):
    def test_inline_push_and_store_plan_is_forwarded_to_all_runner_paths(self) -> None:
        data = b"opaque-kv-bundle"
        raw = _base_request()
        raw["input"]["kv_cache"] = _inline_directive(data)
        resolved = resolve_request_cache_refs(raw, base_dir=".")
        plan = resolved["input"]["kv_cache_plan"]
        self.assertEqual(plan["format"], KV_CACHE_PLAN_FORMAT)
        self.assertEqual(plan["operation"], "load_store")
        self.assertEqual(plan["miss_policy"], "fail")
        self.assertEqual(plan["load"]["transport"], "inline")
        self.assertEqual(plan["load"]["sha256"], _sha(data))
        self.assertIn("batch_key_hash", plan)

        request = InferenceRequest.from_json(resolved)
        profile = ProfileRegistry.load(PROFILES).get("qwen3_6_27b_fp8_efficient_v1")
        item = model_batch_item(request, profile)
        self.assertEqual(item["kv_cache"], plan)
        self.assertEqual(item["extra_body"]["ds4_kv_cache"], plan)

        runner = CapturingRunner()
        runner.run_one(request, profile)
        self.assertEqual(runner.payloads[0]["extra_body"]["ds4_kv_cache"], plan)

    def test_pull_request_blob_and_local_store_modes_normalize(self) -> None:
        remote = normalize_kv_cache_directive(
            {
                "format": "ds4-kv-cache-directive-v1",
                "cache_id": "dsv4:lm:remote",
                "load": {
                    "mode": "prefer",
                    "transport": "remote_uri",
                    "uri": "https://cache.example/dsv4/kv/remote",
                    "bytes": 7 * 1024 * 1024 * 1024,
                    "sha256": "sha256:" + "1" * 64,
                },
            }
        )
        self.assertEqual(remote["operation"], "load")
        self.assertEqual(remote["miss_policy"], "compute")
        self.assertEqual(remote["load"]["transport"], "remote_uri")

        blob = normalize_kv_cache_directive(
            {
                "format": "ds4-kv-cache-directive-v1",
                "cache_id": "qwen27:request-blob",
                "load": {
                    "mode": "require",
                    "transport": "request_blob",
                    "blob_id": "kv0",
                    "bytes": 1024,
                    "sha256": "sha256:" + "2" * 64,
                },
            }
        )
        self.assertEqual(blob["load"]["blob_id"], "kv0")

        local = normalize_kv_cache_directive(
            {
                "format": "ds4-kv-cache-directive-v1",
                "cache_id": "dsv4:local-store",
                "load": {
                    "mode": "require",
                    "transport": "local_store",
                    "cache_key": "spark4/dsv4/prefix-a",
                    "sha256": "sha256:" + "3" * 64,
                },
            }
        )
        self.assertEqual(local["route_affinity"], "required")

    def test_batch_key_includes_kv_cache_plan_hash(self) -> None:
        raw_a = _base_request("a")
        raw_b = _base_request("b")
        raw_a["input"]["kv_cache"] = _inline_directive(b"a")
        raw_b["input"]["kv_cache"] = _inline_directive(b"b")
        req_a = InferenceRequest.from_json(resolve_request_cache_refs(raw_a, base_dir="."))
        req_b = InferenceRequest.from_json(resolve_request_cache_refs(raw_b, base_dir="."))
        profile = ProfileRegistry.load(PROFILES).get("qwen3_6_27b_fp8_efficient_v1")
        self.assertNotEqual(request_batch_key(req_a, profile, None), request_batch_key(req_b, profile, None))

    def test_queue_rejects_unresolved_kv_cache_directive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = _base_request()
            raw["input"]["kv_cache"] = _inline_directive(b"opaque")
            queue = InferenceQueue(tmp)
            with self.assertRaisesRegex(ValueError, "input.kv_cache must be resolved before queueing"):
                queue.submit_requests(
                    requests=[InferenceRequest.from_json(raw)],
                    registry=ProfileRegistry.load(PROFILES),
                    batch_id="batch-a",
                )

    def test_inline_push_fails_closed_before_decoding_oversized_payloads(self) -> None:
        with patch.dict("os.environ", {"DS4_KV_CACHE_MAX_INLINE_BUNDLE_BYTES": "4"}):
            payload = _inline_directive(b"12345")
            payload["load"]["data_b64"] = "not valid base64, but size gate should fire first"
            with self.assertRaisesRegex(ValueError, "exceeds max_inline_bytes"):
                normalize_kv_cache_directive(payload)

    def test_inline_push_rejects_corrupt_payloads(self) -> None:
        payload = _inline_directive(b"abc")
        payload["load"]["data_b64"] = "?"
        with self.assertRaisesRegex(ValueError, "invalid base64"):
            normalize_kv_cache_directive(payload)
        payload = _inline_directive(b"abc")
        payload["load"]["sha256"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
            normalize_kv_cache_directive(payload)

    def test_fuzzed_kv_cache_directives_fail_cleanly(self) -> None:
        rng = random.Random(0xD54CACA0)
        for _ in range(300):
            raw = _base_request("fuzz")
            raw["input"]["kv_cache"] = _fuzz_value(rng, depth=3)
            try:
                resolved = resolve_request_cache_refs(raw, base_dir=".")
            except ValueError:
                continue
            if "kv_cache_plan" not in resolved["input"]:
                continue
            plan = resolved["input"]["kv_cache_plan"]
            self.assertEqual(plan["format"], KV_CACHE_PLAN_FORMAT)
            json.dumps(plan, sort_keys=True)


def _fuzz_value(rng: random.Random, *, depth: int) -> object:
    atoms: list[object] = [None, True, False, "", "x", "sha256:" + "a" * 64, -1, 0, 1, 1024]
    if depth <= 0:
        return rng.choice(atoms)
    kind = rng.randrange(5)
    if kind == 0:
        return rng.choice(atoms)
    if kind == 1:
        return [_fuzz_value(rng, depth=depth - 1) for _ in range(rng.randrange(4))]
    if kind == 2:
        return {str(_fuzz_value(rng, depth=0)): _fuzz_value(rng, depth=depth - 1) for _ in range(rng.randrange(5))}
    if kind == 3:
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(8)))
        directive = _inline_directive(data)
        if rng.randrange(3) == 0:
            directive["load"]["bytes"] = rng.choice([-1, "bad", 10**12])
        if rng.randrange(3) == 0:
            directive["load"]["transport"] = rng.choice(["inline", "remote_uri", "bad"])
        return directive
    return {
        "format": rng.choice(["ds4-kv-cache-directive-v1", "bad", None]),
        "cache_id": rng.choice(["cache-a", "", None]),
        "load": _fuzz_value(rng, depth=depth - 1),
        "store": _fuzz_value(rng, depth=depth - 1),
    }


if __name__ == "__main__":
    unittest.main()
