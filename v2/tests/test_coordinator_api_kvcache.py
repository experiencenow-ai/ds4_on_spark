from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ds4_infer.api import CoordinatorApi
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import FakeRunner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.pipelines import PipelineService, even_layer_partition
from ds4_infer.topology import SparkTopology

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"


class CoordinatorApiKvCacheTests(unittest.TestCase):
    def test_openai_chat_shape_uses_spark0_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake", sync_timeout_s=3)
            code, payload = api.handle_post(
                "/v1/chat/completions",
                {
                    "model": "qwen27_bf16_pp8",
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": 16,
                },
            )
            self.assertEqual(code, 200)
            self.assertEqual(payload["object"], "chat.completion")
            self.assertEqual(payload["choices"][0]["message"]["role"], "assistant")
            request = payload["ds4"]["request"]
            self.assertEqual(request["selected_node_id"], "spark0")
            self.assertEqual(request["selected_service_id"], "qwen27_bf16_pp8")
            self.assertEqual(request["selected_compute_domain"], "spark-fleet-0")

    def test_anthropic_message_shape_uses_same_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake", sync_timeout_s=3)
            code, payload = api.handle_post(
                "/v1/messages",
                {
                    "model": "deepseek-ai/DeepSeek-V4-Flash",
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": 16,
                    "metadata": {"job_class": "tool_chat"},
                },
            )
            self.assertEqual(code, 200)
            self.assertEqual(payload["type"], "message")
            self.assertEqual(payload["role"], "assistant")
            self.assertEqual(payload["ds4"]["request"]["selected_service_id"], "dsv4_flash_pp8")

    def test_external_kv_manifest_is_pipeline_sharded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            code, declared = api.handle_post(
                "/ds4/kvcache/declare",
                {
                    "namespace": "centaur.longmem",
                    "kv_key": "doc:abc",
                    "service_id": "qwen27_bf16_pp8",
                    "total_bytes": 8000,
                    "total_tokens": 4096,
                    "owner": "longmem",
                    "metadata": {"use": "world-model-prefix"},
                },
            )
            self.assertEqual(code, 200)
            self.assertEqual(declared["state"], "declared")
            self.assertEqual(len(declared["shards"]), 8)
            self.assertEqual({shard["bytes"] for shard in declared["shards"]}, {1000})
            self.assertEqual(declared["shards"][0]["layer_start"], 0)
            self.assertEqual(declared["shards"][-1]["layer_end"], 64)
            code, prefetched = api.handle_post(
                "/ds4/kvcache/prefetch",
                {"namespace": "centaur.longmem", "kv_key": "doc:abc", "service_id": "qwen27_bf16_pp8"},
            )
            self.assertEqual(code, 202)
            self.assertFalse(prefetched["prefetch"]["gpu_jit_load"])
            self.assertEqual({shard["state"] for shard in prefetched["shards"]}, {"prefetch_requested"})
            code, committed = api.handle_post(
                "/ds4/kvcache/commit",
                {"namespace": "centaur.longmem", "kv_key": "doc:abc", "service_id": "qwen27_bf16_pp8"},
            )
            self.assertEqual(code, 200)
            self.assertEqual(committed["state"], "available")
            self.assertEqual({shard["state"] for shard in committed["shards"]}, {"ready_on_ssd"})

    def test_openai_external_kv_shorthand_reaches_queue_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            code, payload = api.handle_post(
                "/v1/completions",
                {
                    "model": "qwen27_bf16_pp8",
                    "prompt": "reuse the prefix",
                    "max_tokens": 16,
                    "ds4_async": True,
                    "external_kv": {"namespace": "centaur.longmem", "kv_key": "wm:event-prefix:42"},
                },
            )
            self.assertEqual(code, 202)
            con = sqlite3.connect(Path(tmp) / "queue.sqlite3")
            row = con.execute("select request_json,kv_key from requests where request_id=?", (payload["request_id"],)).fetchone()
            con.close()
            self.assertIsNotNone(row)
            request = json.loads(row[0])
            plan = request["input"]["kv_cache_plan"]
            self.assertEqual(row[1], "wm:event-prefix:42")
            self.assertEqual(plan["format"], "ds4-kv-cache-plan-v1")
            self.assertEqual(plan["load"]["transport"], "external_manifest")
            self.assertEqual(plan["load"]["namespace"], "centaur.longmem")
            self.assertEqual(plan["load"]["service_id"], "qwen27_bf16_pp8")

    def test_openai_external_kv_compute_and_store_requests_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            code, payload = api.handle_post(
                "/v1/completions",
                {
                    "model": "qwen27_bf16_pp8",
                    "prompt": "reuse the prefix",
                    "max_tokens": 16,
                    "ds4_async": True,
                    "external_kv": {
                        "namespace": "centaur.longmem",
                        "kv_key": "wm:event-prefix:42",
                        "miss_policy": "compute_and_store",
                    },
                },
            )
            self.assertEqual(code, 202)
            con = sqlite3.connect(Path(tmp) / "queue.sqlite3")
            row = con.execute("select request_json from requests where request_id=?", (payload["request_id"],)).fetchone()
            con.close()
            self.assertIsNotNone(row)
            request = json.loads(row[0])
            plan = request["input"]["kv_cache_plan"]
            self.assertEqual(plan["miss_policy"], "compute_and_store")
            self.assertEqual(plan["operation"], "load_store")
            self.assertEqual(plan["store"]["mode"], "write_back")
            self.assertEqual(plan["store"]["transport"], "external_manifest")
            self.assertEqual(plan["store"]["namespace"], "centaur.longmem")
            self.assertEqual(plan["store"]["service_id"], "qwen27_bf16_pp8")

    def test_openai_completion_prompt_array_expands_one_api_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake", sync_timeout_s=3)
            code, payload = api.handle_post(
                "/v1/completions",
                {
                    "model": "qwen27_bf16_pp8",
                    "prompt": ["alpha", "beta", "gamma"],
                    "max_tokens": 8,
                    "batch_id": "prompt-array",
                },
            )
            self.assertEqual(code, 200)
            self.assertEqual(payload["object"], "text_completion")
            self.assertEqual(len(payload["choices"]), 3)
            self.assertEqual(payload["ds4"]["batch_id"], "prompt-array")
            status = api.queue.status(batch_id="prompt-array")
            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["completed_count"], 3)

    def test_external_kv_lease_pin_and_evict_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            api.handle_post("/ds4/kvcache/declare", {"kv_key": "stable-prefix", "service_id": "qwen27_bf16_pp8", "total_bytes": 80})
            code, leased = api.handle_post("/ds4/kvcache/lease", {"kv_key": "stable-prefix", "service_id": "qwen27_bf16_pp8", "owner": "diamondizer", "mode": "read"})
            self.assertEqual(code, 200)
            self.assertEqual(leased["lease"]["mode"], "read")
            code, pinned = api.handle_post("/ds4/kvcache/pin", {"kv_key": "stable-prefix", "service_id": "qwen27_bf16_pp8"})
            self.assertEqual(code, 200)
            self.assertEqual(pinned["pin_count"], 1)
            with self.assertRaises(ValueError):
                api.handle_post("/ds4/kvcache/evict", {"kv_key": "stable-prefix", "service_id": "qwen27_bf16_pp8"})
            code, released = api.handle_post("/ds4/kvcache/release", {"lease_id": leased["lease"]["lease_id"]})
            self.assertEqual(code, 200)
            self.assertTrue(released["released"])
            api.handle_post("/ds4/kvcache/unpin", {"kv_key": "stable-prefix", "service_id": "qwen27_bf16_pp8"})
            code, evicted = api.handle_post("/ds4/kvcache/evict", {"kv_key": "stable-prefix", "service_id": "qwen27_bf16_pp8"})
            self.assertEqual(code, 200)
            self.assertEqual(evicted["state"], "evicted")


    def test_external_kv_list_and_touch_for_centaur_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            api.handle_post(
                "/ds4/kvcache/declare",
                {
                    "namespace": "centaur.longmem",
                    "kv_key": "wm:event:0001",
                    "service_id": "qwen27_bf16_pp8",
                    "total_bytes": 8000,
                    "owner": "world-model",
                    "metadata": {"kind": "event-prefix", "tags": ["wm", "events"]},
                },
            )
            api.handle_post(
                "/ds4/kvcache/declare",
                {
                    "namespace": "centaur.longmem",
                    "kv_key": "cc:unit:0001",
                    "service_id": "qwen27_bf16_pp8",
                    "total_bytes": 4000,
                    "owner": "c-compiler",
                    "metadata": {"kind": "compile-context", "tags": ["cc"]},
                },
            )
            code, touched = api.handle_post(
                "/ds4/kvcache/touch",
                {
                    "namespace": "centaur.longmem",
                    "kv_key": "wm:event:0001",
                    "service_id": "qwen27_bf16_pp8",
                    "priority": 5,
                    "metadata": {"diamond_level": 2},
                },
            )
            self.assertEqual(code, 200)
            self.assertEqual(touched["priority"], 5)
            self.assertEqual(touched["metadata"]["diamond_level"], 2)
            code, listed = api.handle_post(
                "/ds4/kvcache/list",
                {"namespace": "centaur.longmem", "service_id": "qwen27_bf16_pp8", "prefix": "wm:", "include_shards": True},
            )
            self.assertEqual(code, 200)
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["objects"][0]["kv_key"], "wm:event:0001")
            self.assertEqual(len(listed["objects"][0]["shards"]), 8)

    def test_dsv4_scheduler_respects_pipeline_service_queue_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            requests = [
                InferenceRequest.from_json(
                    {
                        "format": "ds4-inference-request-v1",
                        "request_id": f"dsv4-{index}",
                        "capability": "smartest",
                        "chat": True,
                        "immediate": False,
                        "job_class": "tool_chat",
                        "max_output_tokens": 64,
                        "thinking_budget_tokens": 0,
                        "temperature": 0,
                        "input": {"messages": [{"role": "user", "content": "x"}]},
                        "output_contract": {"format": "text"},
                    }
                )
                for index in range(12)
            ]
            api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id="dsv4-batch")
            worked = api._work_once({"batch_id": "dsv4-batch", "limit": 48, "concurrency": 48, "batch_linger_s": 0})
            self.assertEqual(worked["claimed_count"], 12)
            self.assertEqual(worked["completed_count"], 12)
            self.assertEqual(api.queue.status(batch_id="dsv4-batch")["completed_count"], 12)


class PipelineAllocatorTests(unittest.TestCase):
    def test_even_layer_partition_for_arbitrary_n(self) -> None:
        self.assertEqual(even_layer_partition(10, 3), (4, 3, 3))
        self.assertEqual(even_layer_partition(64, 7), (10, 9, 9, 9, 9, 9, 9))

    def test_layer_partition_by_node_override(self) -> None:
        known = {"spark0", "spark1", "spark2"}
        service = PipelineService.from_json(
            {
                "service_id": "mini_pp3",
                "profile_id": "mini_profile",
                "model_id": "mini/model",
                "entry_node_id": "spark0",
                "node_ids": ["spark0", "spark1", "spark2"],
                "api_base_url": "http://127.0.0.1:8999",
                "total_layers": 10,
                "layer_partition_by_node": {"spark0": 2, "spark1": 5, "spark2": 3},
            },
            known_node_ids=known,
        )
        self.assertEqual(service.layer_partition, (2, 5, 3))
        self.assertEqual(service.layer_partition_source, "by_node")
        self.assertEqual([(stage.layer_start, stage.layer_end) for stage in service.stages()], [(0, 2), (2, 7), (7, 10)])

    def test_layer_partition_by_node_validates_sum(self) -> None:
        with self.assertRaises(ValueError):
            PipelineService.from_json(
                {
                    "service_id": "bad_pp3",
                    "profile_id": "mini_profile",
                    "model_id": "mini/model",
                    "entry_node_id": "spark0",
                    "node_ids": ["spark0", "spark1", "spark2"],
                    "api_base_url": "http://127.0.0.1:8999",
                    "total_layers": 10,
                    "layer_partition_by_node": {"spark0": 2, "spark1": 5, "spark2": 2},
                },
                known_node_ids={"spark0", "spark1", "spark2"},
            )


if __name__ == "__main__":
    unittest.main()
