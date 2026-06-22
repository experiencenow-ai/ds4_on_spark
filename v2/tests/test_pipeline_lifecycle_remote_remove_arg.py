from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_pipeline_lifecycle.py"


def load_script(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


class PipelineLifecycleRemoteRemoveArgTests(unittest.TestCase):
    def test_remote_launch_removes_exec_arg_and_value(self) -> None:
        lifecycle = load_script(SCRIPT)
        code = lifecycle._remote_launch_script_env_override_code()
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "start.sh"
            script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "exec env A=1 /bin/echo ok --kv-transfer-config '{\"kv_connector\":\"LMCacheConnectorV1\"}' --max-num-seqs 1 --flag",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            old_env = {
                key: os.environ.get(key)
                for key in (
                    "SCRIPT",
                    "DS4_REMOTE_ENV_OVERRIDES",
                    "DS4_REMOTE_ARG_OVERRIDES",
                    "DS4_REMOTE_REMOVE_ARG_OVERRIDES",
                    "DS4_REMOTE_SET_ARG_OVERRIDES",
                )
            }
            try:
                os.environ["SCRIPT"] = str(script)
                os.environ["DS4_REMOTE_ENV_OVERRIDES"] = "{}"
                os.environ["DS4_REMOTE_ARG_OVERRIDES"] = "[]"
                os.environ["DS4_REMOTE_REMOVE_ARG_OVERRIDES"] = json.dumps(["--kv-transfer-config"])
                os.environ["DS4_REMOTE_SET_ARG_OVERRIDES"] = "[]"
                exec(code, {})
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

            rewritten = script.read_text(encoding="utf-8")

        self.assertNotIn("--kv-transfer-config", rewritten)
        self.assertNotIn("LMCacheConnectorV1", rewritten)
        self.assertIn("--max-num-seqs 1", rewritten)
        self.assertIn("--flag", rewritten)

    def test_remote_remove_arg_requires_bare_option_name(self) -> None:
        lifecycle = load_script(SCRIPT)

        self.assertEqual(lifecycle._parse_remote_remove_args(["--kv-transfer-config"]), ["--kv-transfer-config"])
        with self.assertRaisesRegex(ValueError, "invalid"):
            lifecycle._parse_remote_remove_args(["--kv-transfer-config={}"])
        with self.assertRaisesRegex(ValueError, "invalid"):
            lifecycle._parse_remote_remove_args(["kv-transfer-config"])


if __name__ == "__main__":
    unittest.main()
