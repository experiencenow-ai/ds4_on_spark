import importlib.util
import json
import os
import sys
import tempfile
import unittest


def load_proxy(env):
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, "scripts", "ds4_vllm_lazy_proxy.py")
    old = os.environ.copy()
    os.environ.clear()
    os.environ.update(old)
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location("ds4_vllm_lazy_proxy_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return(module)
    finally:
        os.environ.clear()
        os.environ.update(old)


def add_hf_model(root, rel, cfg):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    with open(os.path.join(path, "tokenizer_config.json"), "w", encoding="utf-8") as f:
        json.dump({}, f)
    with open(os.path.join(path, "model.safetensors"), "wb") as f:
        f.write(b"x")


class Ds4VllmLazyProxyTest(unittest.TestCase):
    def test_default_gb10_gateway_tuning_is_applied(self):
        with tempfile.TemporaryDirectory() as td:
            hf = os.path.join(td, "hf")
            add_hf_model(hf, "Qwen/Qwen3.5-4B", {"model_type": "qwen3", "max_position_embeddings": 262144})
            module = load_proxy({
                "MODELS_ROOT": hf,
                "GGUF_MODELS_ROOT": os.path.join(td, "gguf"),
                "DEEPSEEK_V4_REMOTE_BASE": "",
                "VLLM_HOME": "/opt/vllm",
                "PYHDR_HOME": os.path.join(td, "pyhdr"),
                "LOG_DIR": os.path.join(td, "logs"),
            })
            state = module.STATE
            rec = state.models["Qwen/Qwen3.5-4B"]
            args = state.vllm_args("Qwen/Qwen3.5-4B", rec)
            self.assertIn("--enable-chunked-prefill", args)
            self.assertIn("--enable-prefix-caching", args)
            self.assertIn("--async-scheduling", args)
            self.assertEqual(args[args.index("--max-num-seqs") + 1], "64")
            self.assertEqual(args[args.index("--max-num-batched-tokens") + 1], "32768")
            self.assertEqual(args[args.index("--gpu-memory-utilization") + 1], "0.75")
            self.assertEqual(args[args.index("--reasoning-parser") + 1], "qwen3")

    def test_tuning_json_overrides_and_speculative_config(self):
        with tempfile.TemporaryDirectory() as td:
            hf = os.path.join(td, "hf")
            add_hf_model(hf, "Qwen/Qwen3.6-27B-FP8", {"model_type": "qwen3", "max_position_embeddings": 262144})
            tuning = {
                "models": {
                    "Qwen/Qwen3.6-27B-FP8": {
                        "max_num_seqs": 16,
                        "gpu_memory_utilization": "0.85",
                        "speculative_config": {"method": "dflash", "model": "/models/dflash", "num_speculative_tokens": 15},
                        "extra_args": "--attention-backend flash_attn",
                    }
                }
            }
            module = load_proxy({
                "MODELS_ROOT": hf,
                "GGUF_MODELS_ROOT": os.path.join(td, "gguf"),
                "DEEPSEEK_V4_REMOTE_BASE": "",
                "VLLM_HOME": "/opt/vllm",
                "PYHDR_HOME": os.path.join(td, "pyhdr"),
                "LOG_DIR": os.path.join(td, "logs"),
                "DS4_GATEWAY_TUNING_JSON": json.dumps(tuning),
            })
            state = module.STATE
            rec = state.models["Qwen/Qwen3.6-27B-FP8"]
            args = state.vllm_args("Qwen/Qwen3.6-27B-FP8", rec)
            self.assertEqual(args[args.index("--max-num-seqs") + 1], "16")
            self.assertEqual(args[args.index("--gpu-memory-utilization") + 1], "0.85")
            self.assertEqual(json.loads(args[args.index("--speculative-config") + 1])["method"], "dflash")
            self.assertEqual(args[args.index("--attention-backend") + 1], "flash_attn")

    def test_resident_models_use_dedicated_ports_and_tuning(self):
        with tempfile.TemporaryDirectory() as td:
            hf = os.path.join(td, "hf")
            add_hf_model(hf, "Qwen/Qwen3.6-27B-FP8", {"model_type": "qwen3", "max_position_embeddings": 262144})
            add_hf_model(hf, "Qwen/Qwen3.6-35B-A3B-FP8", {"model_type": "qwen3", "max_position_embeddings": 262144})
            resident = [
                {"model": "Qwen/Qwen3.6-27B-FP8", "port": 18100, "tuning": {"gpu_memory_utilization": "0.44", "max_num_seqs": "32"}},
                {"model": "Qwen/Qwen3.6-35B-A3B-FP8", "port": 18101, "tuning": {"gpu_memory_utilization": "0.28", "max_num_seqs": "64"}},
            ]
            module = load_proxy({
                "MODELS_ROOT": hf,
                "GGUF_MODELS_ROOT": os.path.join(td, "gguf"),
                "DEEPSEEK_V4_REMOTE_BASE": "",
                "VLLM_HOME": "/opt/vllm",
                "PYHDR_HOME": os.path.join(td, "pyhdr"),
                "LOG_DIR": os.path.join(td, "logs"),
                "DS4_RESIDENT_MODELS_JSON": json.dumps(resident),
                "DS4_RESIDENT_START": "0",
            })
            state = module.STATE
            self.assertEqual([spec["model"] for spec in state.resident_specs], ["Qwen/Qwen3.6-27B-FP8", "Qwen/Qwen3.6-35B-A3B-FP8"])
            self.assertEqual([spec["port"] for spec in state.resident_specs], [18100, 18101])
            args0 = state.args("Qwen/Qwen3.6-27B-FP8", rec=state.resident_specs[0]["rec"], port=18100)
            args1 = state.args("Qwen/Qwen3.6-35B-A3B-FP8", rec=state.resident_specs[1]["rec"], port=18101)
            self.assertEqual(args0[args0.index("--port") + 1], "18100")
            self.assertEqual(args1[args1.index("--port") + 1], "18101")
            self.assertEqual(args0[args0.index("--gpu-memory-utilization") + 1], "0.44")
            self.assertEqual(args1[args1.index("--gpu-memory-utilization") + 1], "0.28")
            self.assertEqual(args0[args0.index("--max-num-seqs") + 1], "32")
            self.assertEqual(args1[args1.index("--max-num-seqs") + 1], "64")

    def test_local_dflash_drafter_is_auto_attached(self):
        with tempfile.TemporaryDirectory() as td:
            hf = os.path.join(td, "hf")
            dflash_root = os.path.join(hf, "z-lab")
            add_hf_model(hf, "Qwen/Qwen3.5-9B", {"model_type": "qwen3", "max_position_embeddings": 32768})
            os.makedirs(os.path.join(dflash_root, "Qwen3.5-9B-DFlash"), exist_ok=True)
            with open(os.path.join(dflash_root, "Qwen3.5-9B-DFlash", "config.json"), "w", encoding="utf-8") as f:
                json.dump({"model_type": "qwen3_dflash"}, f)
            module = load_proxy({
                "MODELS_ROOT": hf,
                "GGUF_MODELS_ROOT": os.path.join(td, "gguf"),
                "DS4_DFLASH_ROOT": dflash_root,
                "DEEPSEEK_V4_REMOTE_BASE": "",
                "VLLM_HOME": "/opt/vllm",
                "PYHDR_HOME": os.path.join(td, "pyhdr"),
                "LOG_DIR": os.path.join(td, "logs"),
            })
            state = module.STATE
            rec = state.models["Qwen/Qwen3.5-9B"]
            args = state.vllm_args("Qwen/Qwen3.5-9B", rec)
            spec = json.loads(args[args.index("--speculative-config") + 1])
            self.assertEqual(spec["method"], "dflash")
            self.assertEqual(spec["num_speculative_tokens"], 15)
            self.assertTrue(spec["model"].endswith("Qwen3.5-9B-DFlash"))
            self.assertEqual(args[args.index("--max-num-seqs") + 1], "16")

    def test_batch_api_normalizes_items_and_preserves_one_model(self):
        with tempfile.TemporaryDirectory() as td:
            hf = os.path.join(td, "hf")
            add_hf_model(hf, "Qwen/Qwen3.5-4B", {"model_type": "qwen3", "max_position_embeddings": 32768})
            module = load_proxy({
                "MODELS_ROOT": hf,
                "GGUF_MODELS_ROOT": os.path.join(td, "gguf"),
                "DEEPSEEK_V4_REMOTE_BASE": "",
                "VLLM_HOME": "/opt/vllm",
                "PYHDR_HOME": os.path.join(td, "pyhdr"),
                "LOG_DIR": os.path.join(td, "logs"),
            })
            handler = module.Handler.__new__(module.Handler)
            payload = {
                "model": "Qwen/Qwen3.5-4B",
                "max_tokens": 7,
                "temperature": 0.25,
                "items": [
                    {"custom_id": "a", "prompt": "hello"},
                    {"request": {"messages": [{"role": "user", "content": "second"}], "max_tokens": 3}},
                ],
            }
            items = handler.batch_items(payload)
            self.assertEqual(handler.batch_concurrency(payload), 4)
            self.assertEqual(handler.batch_endpoint(payload), "/v1/chat/completions")
            self.assertEqual(handler.batch_resolved_model(payload, items), "Qwen/Qwen3.5-4B")
            first = handler.batch_item_payload(payload, items[0], "/v1/chat/completions")
            second = handler.batch_item_payload(payload, items[1], "/v1/chat/completions")
            self.assertEqual(first["messages"], [{"role": "user", "content": "hello"}])
            self.assertEqual(first["max_tokens"], 7)
            self.assertEqual(first["temperature"], 0.25)
            self.assertFalse(first["stream"])
            self.assertNotIn("custom_id", first)
            self.assertEqual(second["max_tokens"], 3)

    def test_batch_api_rejects_mixed_models(self):
        with tempfile.TemporaryDirectory() as td:
            hf = os.path.join(td, "hf")
            add_hf_model(hf, "Qwen/Qwen3.5-4B", {"model_type": "qwen3", "max_position_embeddings": 32768})
            add_hf_model(hf, "Qwen/Qwen3.5-9B", {"model_type": "qwen3", "max_position_embeddings": 32768})
            module = load_proxy({
                "MODELS_ROOT": hf,
                "GGUF_MODELS_ROOT": os.path.join(td, "gguf"),
                "DEEPSEEK_V4_REMOTE_BASE": "",
                "VLLM_HOME": "/opt/vllm",
                "PYHDR_HOME": os.path.join(td, "pyhdr"),
                "LOG_DIR": os.path.join(td, "logs"),
            })
            handler = module.Handler.__new__(module.Handler)
            payload = {
                "items": [
                    {"model": "Qwen/Qwen3.5-4B", "prompt": "one"},
                    {"model": "Qwen/Qwen3.5-9B", "prompt": "two"},
                ],
            }
            with self.assertRaises(module.VllmError):
                handler.batch_resolved_model(payload, handler.batch_items(payload))

    def test_cpu_service_batch_runs_builtin_services(self):
        with tempfile.TemporaryDirectory() as td:
            module = load_proxy({
                "MODELS_ROOT": os.path.join(td, "hf"),
                "GGUF_MODELS_ROOT": os.path.join(td, "gguf"),
                "DEEPSEEK_V4_REMOTE_BASE": "",
                "LOG_DIR": os.path.join(td, "logs"),
                "CPU_SERVICE_WORKERS": "2",
                "CPU_SERVICE_MAX_CONCURRENCY": "2",
            })
            cpu = module.CPU
            handler = module.Handler.__new__(module.Handler)
            self.assertTrue(handler.is_cpu_batch(json.dumps({"service": "json_validate", "items": []}).encode()))
            self.assertFalse(handler.is_cpu_batch(json.dumps({"model": "m", "items": []}).encode()))
            items = [
                {"custom_id": "good", "text": '{"ok": true}', "required_keys": ["ok"]},
                {"custom_id": "bad", "text": "not-json"},
            ]
            results = cpu.run_batch("json_validate", items, 2, 5.0)
            self.assertEqual([r["custom_id"] for r in results], ["good", "bad"])
            self.assertTrue(results[0]["ok"])
            self.assertTrue(results[0]["response"]["valid"])
            self.assertTrue(results[1]["ok"])
            self.assertFalse(results[1]["response"]["valid"])
            diff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n+EVOLVE-BLOCK\n-old\n"
            stats = cpu.run_batch("diff_stats", [{"text": diff}], 1, 5.0)[0]["response"]
            self.assertEqual(stats["additions"], 1)
            self.assertEqual(stats["deletions"], 1)
            self.assertTrue(stats["contains_evolve_block"])

    def test_cpu_service_command_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as td:
            commands = {
                "upper": {
                    "argv": [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
                    "allow_stdin": True,
                    "timeout_s": 10,
                }
            }
            module = load_proxy({
                "MODELS_ROOT": os.path.join(td, "hf"),
                "GGUF_MODELS_ROOT": os.path.join(td, "gguf"),
                "DEEPSEEK_V4_REMOTE_BASE": "",
                "LOG_DIR": os.path.join(td, "logs"),
                "CPU_SERVICE_WORKERS": "1",
                "CPU_SERVICE_COMMANDS_JSON": json.dumps(commands),
            })
            result = module.CPU.run_batch("command", [{"name": "upper", "stdin": "ok"}], 1, 5.0)[0]
            self.assertTrue(result["ok"])
            self.assertEqual(result["response"]["returncode"], 0)
            self.assertEqual(result["response"]["stdout"].strip(), "OK")
            missing = module.CPU.run_batch("command", [{"name": "missing"}], 1, 5.0)[0]
            self.assertFalse(missing["ok"])
            self.assertIn("unknown allowlisted command", missing["error"])


if __name__ == "__main__":
    unittest.main()
