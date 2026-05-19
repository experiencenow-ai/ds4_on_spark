import tempfile
import unittest
from pathlib import Path

from scripts import patch_vllm_ds4_pp_safetensors_filter as patcher


WEIGHT_UTILS = """from collections.abc import Callable, Generator

def safetensors_weights_iterator(
    hf_weights_files: list[str],
    use_tqdm_on_load: bool,
    safetensors_load_strategy: str | None = None,
    local_expert_ids: set[int] | None = None,
    *,
    safetensors_prefetch_num_threads: int = DEFAULT_SAFETENSORS_PREFETCH_NUM_THREADS,
    safetensors_prefetch_block_size: int = DEFAULT_SAFETENSORS_PREFETCH_BLOCK_SIZE,
) -> Generator[tuple[str, torch.Tensor], None, None]:
    \"\"\"Iterate over the weights in the model safetensor files.

    When *local_expert_ids* is provided, expert weights not belonging to
    this rank are skipped **before** reading from disk, which drastically
    reduces storage I/O for MoE models under EP.
    \"\"\"
    for st_file in files:
        if safetensors_load_strategy == "eager":
            with open(st_file, "rb") as f:
                state_dict = load(f.read())
            for name, param in state_dict.items():
                if not should_skip_weight(name, local_expert_ids):
                    yield name, param
        elif safetensors_load_strategy == "torchao":
            with safe_open(st_file, framework="pt") as f:
                state_dict = {}
                for name in f.keys():  # noqa: SIM118
                    if should_skip_weight(name, local_expert_ids):
                        continue
                    state_dict[name] = f.get_tensor(name)
        else:
            with safe_open(st_file, framework="pt") as f:
                for name in f.keys():  # noqa: SIM118
                    if should_skip_weight(name, local_expert_ids):
                        continue
                    param = f.get_tensor(name)
                    yield name, param
"""


DEFAULT_LOADER = """import dataclasses
from collections.abc import Generator, Iterable

class DefaultModelLoader(BaseModelLoader):
    def _get_weights_iterator(
        self, source: "Source"
    ) -> Generator[tuple[str, torch.Tensor], None, None]:
        weights_iterator = safetensors_weights_iterator(
            hf_weights_files,
            self.load_config.use_tqdm_on_load,
            self.load_config.safetensors_load_strategy,
            local_expert_ids=self.local_expert_ids,
            safetensors_prefetch_num_threads=(
                self.load_config.safetensors_prefetch_num_threads
            ),
        )
        return ((source.prefix + name, tensor) for (name, tensor) in weights_iterator)

    def get_all_weights(self, model_config, model):
        primary_weights = DefaultModelLoader.Source(
            model_config.model,
            model_config.revision,
            prefix="",
            fall_back_to_pt=getattr(model, "fall_back_to_pt_during_load", True),
            allow_patterns_overrides=getattr(model, "allow_patterns_overrides", None),
        )
        yield from self._get_weights_iterator(primary_weights)
"""


DEEPSEEK_V4 = """class DeepseekV4ForCausalLM(nn.Module, SupportsPP):
    def get_mtp_target_hidden_states(self) -> torch.Tensor | None:
        return getattr(self.model, "_mtp_hidden_buffer", None)

    def load_weights(self, weights: Iterable[tuple[str, torch.Tensor]]) -> set[str]:
        loader = AutoWeightsLoader(self, skip_substrs=["mtp."])
        loaded_params = loader.load_weights(weights, mapper=self.hf_to_vllm_mapper)
        self.model.finalize_mega_moe_weights()
        return loaded_params
"""


class PatchVllmDs4PpSafetensorsFilterTest(unittest.TestCase):
    def test_patch_text_blocks_are_idempotent(self) -> None:
        once = patcher.patch_weight_utils(WEIGHT_UTILS)
        twice = patcher.patch_weight_utils(once)
        self.assertEqual(once, twice)
        self.assertIn("weight_name_filter: Callable[[str], bool] | None = None", once)
        self.assertIn("not weight_name_filter(name)", once)

    def test_patch_package_dir_writes_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vllm"
            (root / "model_executor" / "model_loader").mkdir(parents=True)
            (root / "model_executor" / "models").mkdir(parents=True)
            wu = root / "model_executor" / "model_loader" / "weight_utils.py"
            dl = root / "model_executor" / "model_loader" / "default_loader.py"
            ds = root / "model_executor" / "models" / "deepseek_v4.py"
            wu.write_text(WEIGHT_UTILS, encoding="utf-8")
            dl.write_text(DEFAULT_LOADER, encoding="utf-8")
            ds.write_text(DEEPSEEK_V4, encoding="utf-8")
            result = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertTrue(result["changed"])
            self.assertTrue((wu.with_name(wu.name + ".bak")).exists())
            self.assertIn("should_load_checkpoint_weight", ds.read_text(encoding="utf-8"))
            result2 = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertFalse(result2["changed"])


if __name__ == "__main__":
    unittest.main()
