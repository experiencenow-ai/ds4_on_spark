from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from ds4_infer.profiles import ProfileRegistry
from ds4_kvcache.cli import main as kvcache_cli_main
from ds4_kvcache.service import KvCacheDeployment, kv_transfer_config, plan_deployment, write_launch_scripts
from ds4_tools.registry import ToolRegistry


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "profiles" / "kv_cache" / "dsv4_spark45_hma_cpu_offload.json"
QWEN_DEPLOYMENT = ROOT / "profiles" / "kv_cache" / "qwen27_lmcache_mp_spark7.json"
QWEN_PP_DEPLOYMENT = ROOT / "profiles" / "kv_cache" / "qwen27_bf16_pp8_lmcache_hma.json"
DSV4_PP_DEPLOYMENT = ROOT / "profiles" / "kv_cache" / "dsv4_flash_pp8_simple_offload.json"
GEMMA31_PP_DEPLOYMENT = ROOT / "profiles" / "kv_cache" / "gemma4_31b_it_pp8_plain.json"
DSV4_PRODUCTION_PROFILE = ROOT / "profiles" / "production" / "dsv4_flash_pp8_resident128.json"
DSV4_PRODUCTION = json.loads(DSV4_PRODUCTION_PROFILE.read_text(encoding="utf-8"))
VLLM_COMMIT = "c6e55a80d213ba2652ab9a7d5d0aacf01cbccd34"


class KvCachePlanningTests(unittest.TestCase):
    def test_hma_offload_plan_is_single_vllm_instance(self) -> None:
        deployment = KvCacheDeployment.load(DEPLOYMENT)
        plan = plan_deployment(deployment)

        self.assertEqual(plan["format"], "ds4-vllm-kv-cache-launch-plan-v1")
        self.assertEqual(plan["profile_id"], "dsv4_vllm_mtp_smartest_v1")
        self.assertEqual(plan["vllm"]["spark_node"], "spark4")
        self.assertEqual(plan["worker_nodes"], ["spark4", "spark5"])
        self.assertEqual(plan["logical_service_count"], 1)
        self.assertEqual(plan["model_instance_count"], 1)
        self.assertEqual(plan["runtime"]["runtime_contract_id"], "dsv4_spark45_vllm_mtp_v1")
        self.assertEqual(plan["runtime"]["vllm_source_commit"], VLLM_COMMIT)
        self.assertEqual(plan["listen_base_url"], "http://0.0.0.0:8000")
        self.assertEqual(plan["openai_base_url"], "http://spark4:8000")
        self.assertIn("--kv-transfer-config", plan["vllm"]["argv"])
        self.assertIn("--no-disable-hybrid-kv-cache-manager", plan["vllm"]["argv"])
        self.assertEqual(plan["vllm"]["argv"][plan["vllm"]["argv"].index("--max-model-len") + 1], "262144")
        self.assertEqual(plan["vllm"]["argv"][plan["vllm"]["argv"].index("--gpu-memory-utilization") + 1], "0.68")
        self.assertEqual(plan["vllm"]["argv"][plan["vllm"]["argv"].index("--max-num-seqs") + 1], "1")
        self.assertEqual(plan["vllm"]["argv"][plan["vllm"]["argv"].index("--max-num-batched-tokens") + 1], "2048")
        self.assertIn("--speculative-config", plan["vllm"]["argv"])
        self.assertIn("--kv-cache-metrics", plan["vllm"]["argv"])
        self.assertNotIn("LMCacheConnectorV1Dynamic", plan["vllm"]["command"])
        self.assertNotIn("prefiller", plan)
        self.assertNotIn("decoder", plan)
        self.assertNotIn("proxy", plan)

    def test_hma_offload_uses_supported_connector(self) -> None:
        deployment = KvCacheDeployment.load(DEPLOYMENT)
        config = kv_transfer_config(deployment.connector)

        self.assertEqual(config["kv_connector"], "SimpleCPUOffloadConnector")
        self.assertEqual(config["kv_role"], "kv_both")
        self.assertEqual(config["kv_connector_extra_config"]["spec_name"], "SimpleCPUOffloadingSpec")
        self.assertEqual(config["kv_connector_extra_config"]["cpu_bytes_to_use"], "2147483648")
        self.assertTrue(config["kv_connector_extra_config"]["lazy_offload"])
        self.assertNotIn("kv_connector_module_path", config)
        self.assertNotIn("LMCACHE_USE_EXPERIMENTAL", deployment.extra_env)
        self.assertEqual(deployment.extra_env["VLLM_USE_SIMPLE_KV_OFFLOAD"], "1")
        self.assertEqual(deployment.extra_env["PYTHONHASHSEED"], "0")

    def test_dsv4_lmcache_dynamic_is_rejected_until_hma_supported(self) -> None:
        deployment = json.loads(DEPLOYMENT.read_text())
        deployment["connector"] = {
            "connector_id": "lmcache_dynamic",
            "kv_role": "kv_both",
        }
        with self.assertRaisesRegex(ValueError, "SupportsHMA"):
            KvCacheDeployment.from_json(deployment)

    def test_dsv4_plain_offloading_connector_is_rejected(self) -> None:
        deployment = json.loads(DEPLOYMENT.read_text())
        deployment["connector"] = {
            "connector_id": "offloading",
            "kv_role": "kv_both",
        }
        with self.assertRaisesRegex(ValueError, "SimpleCPUOffloadConnector"):
            KvCacheDeployment.from_json(deployment)

    def test_write_launch_scripts(self) -> None:
        deployment = KvCacheDeployment.load(DEPLOYMENT)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_launch_scripts(deployment, tmp)
            install = Path(manifest["scripts"]["install"])
            start = Path(manifest["scripts"]["start_vllm"])
            self.assertTrue(install.exists())
            self.assertTrue(start.exists())
            self.assertIn("no connector packages requested", install.read_text())
            self.assertIn("SimpleCPUOffloadConnector", start.read_text())
            self.assertIn("--no-disable-hybrid-kv-cache-manager", start.read_text())
            self.assertNotIn("LMCacheConnectorV1Dynamic", start.read_text())
            self.assertTrue((Path(tmp) / "kv_cache_launch_manifest.json").exists())

    def test_qwen_lmcache_mp_plan_uses_external_cache_server(self) -> None:
        deployment = KvCacheDeployment.load(QWEN_DEPLOYMENT)
        plan = plan_deployment(deployment)
        config = plan["connector"]["kv_transfer_config"]

        self.assertEqual(plan["profile_id"], "qwen3_6_27b_fp8_efficient_v1")
        self.assertEqual(plan["spark_node"], "spark7")
        self.assertEqual(plan["runtime"]["runtime_contract_id"], "qwen27_vllm_trim_v1")
        self.assertEqual(plan["runtime"]["vllm_fork"], "https://github.com/experiencenow-ai/vllm")
        self.assertEqual(plan["runtime"]["vllm_source_commit"], VLLM_COMMIT)
        self.assertEqual(plan["openai_base_url"], "http://127.0.0.1:18110")
        self.assertEqual(plan["connector"]["install_packages"], ["lmcache==0.4.5"])
        self.assertEqual(plan["connector"]["install_args"], ["--no-build-isolation"])
        self.assertEqual(plan["connector"]["wheel_dir"], "/tmp/ds4_lmcache_wheels")
        self.assertEqual(config["kv_connector"], "LMCacheMPConnector")
        self.assertNotIn("kv_connector_module_path", config)
        self.assertEqual(config["kv_connector_extra_config"]["lmcache.mp.host"], "127.0.0.1")
        self.assertEqual(config["kv_connector_extra_config"]["lmcache.mp.port"], 5555)
        self.assertIn("LMCacheMPConnector", plan["vllm"]["command"])
        self.assertIn("--max-model-len", plan["vllm"]["argv"])
        self.assertIn("--kv-cache-dtype", plan["vllm"]["argv"])
        self.assertEqual(plan["vllm"]["argv"][plan["vllm"]["argv"].index("--kv-cache-dtype") + 1], "fp8")
        self.assertIn("--attention-backend", plan["vllm"]["argv"])
        self.assertEqual(plan["vllm"]["argv"][plan["vllm"]["argv"].index("--attention-backend") + 1], "TRITON_ATTN")
        self.assertIn("--no-disable-hybrid-kv-cache-manager", plan["vllm"]["argv"])
        self.assertEqual(plan["cache_server"]["kind"], "lmcache_mp")
        self.assertEqual(plan["cache_server"]["management_url"], "http://127.0.0.1:18080")
        self.assertIn("--l2-adapter", plan["cache_server"]["argv"])
        self.assertIn("/home/spark7/ds4_nvme/ds4_lmcache/qwen27_fp8kv/l2", plan["cache_server"]["command"])

    def test_write_qwen_lmcache_launch_scripts(self) -> None:
        deployment = KvCacheDeployment.load(QWEN_DEPLOYMENT)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_launch_scripts(deployment, tmp)
            install = Path(manifest["scripts"]["install"]).read_text()
            cache_server = Path(manifest["scripts"]["start_cache_server"]).read_text()
            vllm = Path(manifest["scripts"]["start_vllm"]).read_text()

            self.assertIn("CUDA_HOME=/usr/local/cuda", install)
            self.assertIn("pip wheel --no-build-isolation --no-deps", install)
            self.assertIn("lmcache==0.4.5", install)
            self.assertIn("pip install --no-deps", install)
            self.assertIn('\"${wheel}\"', install)
            self.assertIn("mkdir -p /home/spark7/ds4_nvme/ds4_lmcache/qwen27_fp8kv/l2", install)
            self.assertIn("cd /home/spark7/src/ds4_on_spark/v2", cache_server)
            self.assertIn("exec env CPATH=", cache_server)
            self.assertIn("lmcache server", cache_server)
            self.assertIn("cd /home/spark7/src/ds4_on_spark/v2", vllm)
            self.assertIn("exec env CPATH=", vllm)
            self.assertIn("LMCacheMPConnector", vllm)

    def test_qwen_bf16_pp8_lmcache_hma_plan_is_pipeline_sharded(self) -> None:
        deployment = KvCacheDeployment.load(QWEN_PP_DEPLOYMENT)
        plan = plan_deployment(deployment)

        self.assertEqual(plan["profile_id"], "qwen3_6_27b_bf16_pp8_efficient_v1")
        self.assertEqual(plan["spark_node"], "spark0")
        self.assertEqual(plan["pipeline_parallel_size"], 8)
        self.assertEqual(plan["tensor_parallel_size"], 1)
        self.assertEqual(plan["cache_sharding"], "pipeline_layers")
        self.assertEqual(plan["layer_partition"], [9, 9, 9, 8, 8, 8, 8, 5])
        self.assertEqual(len(plan["vllm_nodes"]), 8)
        self.assertEqual(plan["vllm_nodes"][0]["fabric_ip"], "10.10.100.10")
        self.assertEqual(plan["vllm_nodes"][-1]["fabric_ip"], "10.10.100.17")
        self.assertEqual(plan["vllm_nodes"][0]["layer_start"], 0)
        self.assertEqual(plan["vllm_nodes"][-1]["layer_end"], 64)
        self.assertIn("--language-model-only", plan["vllm_nodes"][0]["argv"])
        self.assertEqual(plan["vllm_nodes"][0]["argv"][4], "/home/spark0/models/hf/Qwen/Qwen3.6-27B")
        self.assertEqual(plan["vllm_nodes"][-1]["argv"][4], "/home/spark7/models/hf/Qwen/Qwen3.6-27B")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["GLOO_SOCKET_IFNAME"], "ds4ring0")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["TP_SOCKET_IFNAME"], "ds4ring0")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["DS4_PP_TRANSPORT"], "tcp-staged")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_EDGE_RAIL"], "enp")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR"], "1")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_TCP_TENSOR_DICT"], "1")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_TCP_STRIPES"], "16")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_TCP_BIND_HOST"], "10.10.100.10")
        self.assertEqual(plan["vllm_nodes"][-1]["env"]["VLLM_DS4_PP_TCP_ADVERTISE_HOST"], "10.10.100.17")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_DIRECT_CUDA_TENSOR_DICT"], "0")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_TORCH_GROUP_WARMUP"], "0")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_HOST_IP"], "10.10.100.10")
        self.assertEqual(plan["vllm_nodes"][-1]["env"]["VLLM_HOST_IP"], "10.10.100.17")
        self.assertIn("--dtype", plan["vllm_nodes"][0]["argv"])
        self.assertEqual(plan["vllm_nodes"][0]["argv"][plan["vllm_nodes"][0]["argv"].index("--dtype") + 1], "bfloat16")
        self.assertIn("--kv-cache-dtype", plan["vllm_nodes"][0]["argv"])
        self.assertEqual(plan["vllm_nodes"][0]["argv"][plan["vllm_nodes"][0]["argv"].index("--kv-cache-dtype") + 1], "fp8")
        self.assertIn("--attention-backend", plan["vllm_nodes"][0]["argv"])
        self.assertEqual(plan["vllm_nodes"][0]["argv"][plan["vllm_nodes"][0]["argv"].index("--attention-backend") + 1], "TRITON_ATTN")
        self.assertIn("LMCacheConnectorV1", plan["vllm_nodes"][0]["command"])
        self.assertIn("VLLM_PP_LAYER_PARTITION=9,9,9,8,8,8,8,5", plan["vllm_nodes"][0]["command"])
        self.assertIn("--headless", plan["vllm_nodes"][-1]["argv"])

    def test_dsv4_flash_pp8_simple_offload_plan_is_pipeline_sharded(self) -> None:
        deployment = KvCacheDeployment.load(DSV4_PP_DEPLOYMENT)
        plan = plan_deployment(deployment)

        self.assertEqual(plan["profile_id"], "dsv4_vllm_mtp_pp8_smartest_v1")
        self.assertEqual(plan["pipeline_parallel_size"], DSV4_PRODUCTION["pipeline_parallel_size"])
        self.assertEqual(plan["cache_sharding"], "pipeline_layers")
        self.assertEqual(plan["layer_partition"], DSV4_PRODUCTION["layer_partition"])
        self.assertEqual(plan["vllm_nodes"][-1]["layer_end"], 43)
        self.assertIn("SimpleCPUOffloadConnector", plan["vllm_nodes"][0]["command"])
        self.assertIn("--kv-cache-dtype", plan["vllm_nodes"][0]["argv"])
        self.assertEqual(plan["vllm_nodes"][0]["argv"][plan["vllm_nodes"][0]["argv"].index("--kv-cache-dtype") + 1], DSV4_PRODUCTION["kv_cache_dtype"])
        self.assertEqual(plan["vllm_nodes"][0]["argv"][plan["vllm_nodes"][0]["argv"].index("--max-num-seqs") + 1], str(DSV4_PRODUCTION["max_num_seqs"]))
        self.assertEqual(plan["vllm_nodes"][0]["argv"][plan["vllm_nodes"][0]["argv"].index("--max-num-batched-tokens") + 1], str(DSV4_PRODUCTION["max_num_batched_tokens"]))
        self.assertEqual(plan["vllm_nodes"][0]["argv"][plan["vllm_nodes"][0]["argv"].index("--kv-cache-memory-bytes") + 1], str(DSV4_PRODUCTION["kv_cache_memory_bytes"]))
        self.assertIn("--headless", plan["vllm_nodes"][-1]["argv"])

    def test_gemma_plain_pipeline_plan_expands_node_templates_without_connector(self) -> None:
        deployment = KvCacheDeployment.load(GEMMA31_PP_DEPLOYMENT)
        plan = plan_deployment(deployment)

        self.assertEqual(plan["profile_id"], "gemma4_31b_it_pp8_peer_v1")
        self.assertEqual(plan["pipeline_parallel_size"], 8)
        self.assertEqual(plan["connector"]["kv_transfer_config"], {})
        self.assertEqual(plan["layer_partition"], [8, 8, 8, 8, 7, 7, 7, 7])
        self.assertNotIn("--kv-transfer-config", plan["vllm_nodes"][0]["argv"])
        self.assertEqual(plan["vllm_nodes"][0]["argv"][:4], ["/home/spark0/standard-runtimes/vllm-main-gdn-nixl/venv/bin/python", "-m", "vllm.entrypoints.cli.main", "serve"])
        self.assertEqual(plan["vllm_nodes"][0]["argv"][4], "/home/spark0/models/hf/google/gemma-4-31B-it")
        self.assertEqual(plan["vllm_nodes"][-1]["argv"][:4], ["/home/spark7/standard-runtimes/vllm-main-gdn-nixl/venv/bin/python", "-m", "vllm.entrypoints.cli.main", "serve"])
        self.assertEqual(plan["vllm_nodes"][-1]["argv"][4], "/home/spark7/models/hf/google/gemma-4-31B-it")
        self.assertEqual(plan["vllm_nodes"][0]["argv"][plan["vllm_nodes"][0]["argv"].index("--master-addr") + 1], "10.10.100.10")
        self.assertEqual(plan["vllm_nodes"][0]["fabric_ip"], "10.10.100.10")
        self.assertEqual(plan["vllm_nodes"][-1]["fabric_ip"], "10.10.100.17")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["GLOO_SOCKET_IFNAME"], "ds4ring0")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["TP_SOCKET_IFNAME"], "ds4ring0")
        self.assertIn("/home/spark0/standard-runtimes/python3.12-dev-extract/usr/include/python3.12", plan["vllm_nodes"][0]["env"]["CPATH"])
        self.assertIn("/home/spark7/standard-runtimes/python3.12-dev-extract/usr/include/python3.12", plan["vllm_nodes"][-1]["env"]["CPATH"])
        self.assertIn("/home/spark0/standard-runtimes/vllm-main-gdn-nixl/venv/bin", plan["vllm_nodes"][0]["env"]["PATH"])
        self.assertIn("/home/spark7/standard-runtimes/vllm-main-gdn-nixl/venv/bin", plan["vllm_nodes"][-1]["env"]["PATH"])
        self.assertEqual(plan["vllm_nodes"][0]["env"]["DS4_PP_TRANSPORT"], "tcp-staged")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_EDGE_RAIL"], "enp")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR"], "1")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_TCP_TENSOR_DICT"], "1")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_TCP_STRIPES"], "16")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_TCP_BIND_HOST"], "10.10.100.10")
        self.assertEqual(plan["vllm_nodes"][-1]["env"]["VLLM_DS4_PP_TCP_ADVERTISE_HOST"], "10.10.100.17")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_DIRECT_CUDA_TENSOR_DICT"], "0")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_DS4_PP_TORCH_GROUP_WARMUP"], "0")
        self.assertEqual(plan["vllm_nodes"][0]["env"]["VLLM_HOST_IP"], "10.10.100.10")
        self.assertEqual(plan["vllm_nodes"][-1]["env"]["VLLM_HOST_IP"], "10.10.100.17")
        self.assertEqual(plan["vllm_nodes"][0]["working_directory"], "/home/spark0/src/ds4_on_spark/v2")
        self.assertEqual(plan["vllm_nodes"][-1]["working_directory"], "/home/spark7/src/ds4_on_spark/v2")
        self.assertEqual(plan["vllm_nodes"][-1]["env"]["PYTHONPATH"], "/home/spark7/src/ds4_on_spark/v2/src")
        self.assertIn("/home/spark7/standard-runtimes/vllm-main-gdn-nixl/vllm/examples/tool_chat_template_gemma4.jinja", plan["vllm_nodes"][-1]["argv"])
        self.assertIn("--headless", plan["vllm_nodes"][-1]["argv"])

    def test_write_pipeline_launch_scripts(self) -> None:
        deployment = KvCacheDeployment.load(QWEN_PP_DEPLOYMENT)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_launch_scripts(deployment, tmp)
            self.assertIn("start_vllm_nodes", manifest["scripts"])
            self.assertEqual(len(manifest["scripts"]["start_vllm_nodes"]), 8)
            rank0 = Path(manifest["scripts"]["start_vllm_nodes"]["spark0"]).read_text()
            rank7 = Path(manifest["scripts"]["start_vllm_nodes"]["spark7"]).read_text()
            self.assertIn("--pipeline-parallel-size 8", rank0)
            self.assertIn("--node-rank 0", rank0)
            self.assertIn("--node-rank 7", rank7)
            self.assertIn("GLOO_SOCKET_IFNAME=ds4ring0", rank0)
            self.assertIn("TP_SOCKET_IFNAME=ds4ring0", rank0)
            self.assertIn("CPATH=/home/spark0/standard-runtimes/python3.12-dev-extract/usr/include", rank0)
            self.assertIn("PATH=/home/spark7/ds4-vllm-local/bin", rank7)
            self.assertIn("DS4_PP_TRANSPORT=tcp-staged", rank0)
            self.assertIn("VLLM_DS4_PP_EDGE_RAIL=enp", rank0)
            self.assertIn("VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR=1", rank0)
            self.assertIn("VLLM_DS4_PP_TCP_TENSOR_DICT=1", rank0)
            self.assertIn("VLLM_DS4_PP_TCP_BIND_HOST=10.10.100.10", rank0)
            self.assertIn("VLLM_DS4_PP_TCP_ADVERTISE_HOST=10.10.100.17", rank7)
            self.assertIn("VLLM_DS4_PP_DIRECT_CUDA_TENSOR_DICT=0", rank0)
            self.assertIn("VLLM_HOST_IP=10.10.100.10", rank0)
            self.assertIn("VLLM_HOST_IP=10.10.100.17", rank7)
            self.assertIn("--headless", rank7)

    def test_static_pipeline_cli_write_scripts_requires_lifecycle_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("DS4_PIPELINE_LIFECYCLE", None)
                with self.assertRaisesRegex(SystemExit, "ds4_pipeline_lifecycle"):
                    kvcache_cli_main(["write-scripts", "--deployment", str(QWEN_PP_DEPLOYMENT), "--output-dir", tmp])

    def test_static_pipeline_cli_write_scripts_allows_lifecycle_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DS4_PIPELINE_LIFECYCLE": "1"}):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(kvcache_cli_main(["write-scripts", "--deployment", str(QWEN_PP_DEPLOYMENT), "--output-dir", tmp]), 0)
            self.assertTrue((Path(tmp) / "kv_cache_launch_manifest.json").exists())

    def test_gemma_pipeline_launch_scripts_use_200g_fabric_host_ips(self) -> None:
        deployment = KvCacheDeployment.load(GEMMA31_PP_DEPLOYMENT)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_launch_scripts(deployment, tmp)
            rank0 = Path(manifest["scripts"]["start_vllm_nodes"]["spark0"]).read_text()
            rank7 = Path(manifest["scripts"]["start_vllm_nodes"]["spark7"]).read_text()
            self.assertIn("GLOO_SOCKET_IFNAME=ds4ring0", rank0)
            self.assertIn("CPATH=/home/spark0/standard-runtimes/python3.12-dev-extract/usr/include", rank0)
            self.assertIn("PATH=/home/spark0/standard-runtimes/vllm-main-gdn-nixl/venv/bin", rank0)
            self.assertIn("TP_SOCKET_IFNAME=ds4ring0", rank0)
            self.assertIn("DS4_PP_TRANSPORT=tcp-staged", rank0)
            self.assertIn("VLLM_DS4_PP_EDGE_RAIL=enp", rank0)
            self.assertIn("VLLM_HOST_IP=10.10.100.10", rank0)
            self.assertIn("VLLM_HOST_IP=10.10.100.17", rank7)

    def test_kv_cache_is_optional_on_existing_profiles(self) -> None:
        registry = ProfileRegistry.load(ROOT / "profiles" / "models")
        dsv4 = registry.get("dsv4_vllm_mtp_smartest_v1")
        qwen = registry.get("qwen3_6_27b_fp8_efficient_v1")

        self.assertEqual(dsv4.backend, "vllm_mtp")
        self.assertEqual(qwen.backend, "vllm")
        self.assertEqual(dsv4.routing["optional_kv_cache_deployments"], ["profiles/kv_cache/dsv4_spark45_hma_cpu_offload.json"])
        self.assertEqual(qwen.routing["optional_kv_cache_deployments"], ["profiles/kv_cache/qwen27_lmcache_mp_spark7.json"])
        pp_dsv4 = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        pp_qwen = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        self.assertEqual(pp_dsv4.routing["optional_kv_cache_deployments"], ["profiles/kv_cache/dsv4_flash_pp8_simple_offload.json"])
        self.assertEqual(pp_qwen.routing["optional_kv_cache_deployments"], ["profiles/kv_cache/qwen27_bf16_pp8_lmcache_hma.json"])
        with self.assertRaisesRegex(ValueError, "no production profile"):
            registry.resolve(capability="smartest", chat=True, job_class="tool_chat")
        pinned = registry.resolve(capability=None, chat=True, job_class="tool_chat", model_pin={"profile_id": pp_dsv4.profile_id})
        self.assertEqual(pinned.profile_id, pp_dsv4.profile_id)
        self.assertEqual(registry.resolve(capability="efficient", chat=False, job_class="atom_edit").profile_id, pp_qwen.profile_id)

    def test_tool_registry_has_kvcache_plan_tool(self) -> None:
        registry = ToolRegistry.load(ROOT / "tools" / "registry.jsonl")
        tool = registry.get("tool:ds4.kvcache.plan")
        self.assertEqual(tool.tool_id, "tool:ds4.kvcache.plan")
        result = registry.invoke("tool:ds4.kvcache.plan", {"deployment": str(DEPLOYMENT)})

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["plan"]["profile_id"], "dsv4_vllm_mtp_smartest_v1")

    def test_plan_is_json_serializable(self) -> None:
        json.dumps(plan_deployment(KvCacheDeployment.load(DEPLOYMENT)), sort_keys=True)


if __name__ == "__main__":
    unittest.main()
