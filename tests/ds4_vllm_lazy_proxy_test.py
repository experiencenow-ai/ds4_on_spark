import importlib.util
import json
import os
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


if __name__ == "__main__":
    unittest.main()
