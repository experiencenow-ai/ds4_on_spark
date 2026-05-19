import tempfile
import unittest
from pathlib import Path

from scripts import patch_vllm_ds4_pp_mxfp4_layerwise_finalize as patcher


DEEPSEEK_V4 = """class DeepseekV4Model(nn.Module):
    def load_weights(self, weights: Iterable[tuple[str, torch.Tensor]]) -> set[str]:
        params_dict = dict(self.named_parameters())
        loaded_params: set[str] = set()

        # TP for attention
        tp_size = get_tensor_model_parallel_world_size()
        tp_rank = get_tensor_model_parallel_rank()
        n_head = self.config.num_attention_heads
        n_local_head = n_head // tp_size
        head_rank_start = n_local_head * tp_rank
        head_rank_end = n_local_head * (tp_rank + 1)

        # Pre-compute expert mapping ONCE.
        expert_mapping = self.get_expert_mapping()

        for name, loaded_weight in weights:
            if ".experts." in name:
                for mapping in expert_mapping:
                    param_name, weight_name, expert_id, shard_id = mapping
                    if weight_name not in name:
                        continue
                    name_mapped = name.replace(weight_name, param_name)
                    param = params_dict[name_mapped]
                    weight_loader = typing.cast(
                        Callable[..., bool], param.weight_loader
                    )
                    success = weight_loader(
                        param,
                        loaded_weight,
                        name_mapped,
                        shard_id=shard_id,
                        expert_id=expert_id,
                        return_success=True,
                    )
                        if success:
                            name = name_mapped
                            break
                    loaded_params.add(name_mapped)
                continue
        return loaded_params
"""


MXFP4_METHODS = """class GptOssMxfp4MoEMethod(FusedMoEMethodBase):
    def process_weights_after_loading(self, layer):
        w13 = layer.w13_weight
        w2 = layer.w2_weight
        w13_scale = layer.w13_weight_scale
        w2_scale = layer.w2_weight_scale
        w13_bias = getattr(layer, "w13_bias", None)
        w2_bias = getattr(layer, "w2_bias", None)

        if self.mxfp4_backend == Mxfp4MoeBackend.NONE:
            return

        self._setup_kernel(layer, w13, w2, w13_scale, w2_scale, w13_bias, w2_bias)

class Mxfp4MoEMethod(FusedMoEMethodBase):
    def process_weights_after_loading(self, layer):
        w13 = layer.w13_weight
        w2 = layer.w2_weight
        w13_scale = layer.w13_weight_scale
        w2_scale = layer.w2_weight_scale
        w13_bias = getattr(layer, "w13_bias", None)
        w2_bias = getattr(layer, "w2_bias", None)

        if self.mxfp4_backend == Mxfp4MoeBackend.NONE:
            return

        self._setup_kernel(layer, w13, w2, w13_scale, w2_scale, w13_bias, w2_bias)
"""


class PatchVllmDs4PpMxfp4LayerwiseFinalizeTest(unittest.TestCase):
    def test_deepseek_patch_adds_layerwise_finalize_hook(self) -> None:
        once = patcher.patch_deepseek_v4(DEEPSEEK_V4)
        twice = patcher.patch_deepseek_v4(once)
        self.assertEqual(once, twice)
        self.assertIn("expert_layer_load_hits", once)
        self.assertIn("maybe_finalize_layer_experts(", once)
        self.assertIn("torch.cuda.empty_cache()", once)
        self.assertIn("process(experts)", once)
        self.assertIn("del params_dict[param_key]", once)

    def test_deepseek_patch_upgrades_prior_layerwise_helper(self) -> None:
        current = patcher.patch_deepseek_v4(DEEPSEEK_V4)
        cleanup = """            for param_key in list(params_dict):
                if param_key.startswith(f"layers.{layer_idx}.ffn.experts."):
                    del params_dict[param_key]
"""
        previous = current.replace(cleanup, "")
        self.assertNotIn("del params_dict[param_key]", previous)
        self.assertEqual(patcher.patch_deepseek_v4(previous), current)

    def test_mxfp4_patch_guards_global_postprocess(self) -> None:
        once = patcher.patch_mxfp4(MXFP4_METHODS)
        twice = patcher.patch_mxfp4(once)
        self.assertEqual(once, twice)
        self.assertEqual(once.count("_ds4_layerwise_finalized"), 4)
        self.assertEqual(once.count("self._setup_kernel("), 2)

    def test_patch_package_dir_writes_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vllm"
            (root / "model_executor" / "models").mkdir(parents=True)
            (root / "model_executor" / "layers" / "quantization").mkdir(parents=True)
            ds = root / "model_executor" / "models" / "deepseek_v4.py"
            mx = root / "model_executor" / "layers" / "quantization" / "mxfp4.py"
            ds.write_text(DEEPSEEK_V4, encoding="utf-8")
            mx.write_text(MXFP4_METHODS, encoding="utf-8")
            result = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertTrue(result["changed"])
            self.assertTrue((ds.with_name(ds.name + ".bak")).exists())
            self.assertTrue((mx.with_name(mx.name + ".bak")).exists())
            result2 = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertFalse(result2["changed"])


if __name__ == "__main__":
    unittest.main()
