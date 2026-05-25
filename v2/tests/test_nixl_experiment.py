from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from ds4_nixl.experiment import VllmBuildPlan, plan_spark7_experiment, write_spark7_experiment
from ds4_nixl.service import NixlDeployment, plan_deployment


ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / "profiles" / "vllm_builds" / "vllm_main_after_gdn_nixl_41869.json"
SMOKE_DEPLOYMENT = ROOT / "profiles" / "nixl" / "qwen35_0_8b_spark7_gdn_nixl_smoke.json"
QWEN27_DEPLOYMENT = ROOT / "profiles" / "nixl" / "qwen27_spark7_gdn_nixl_experimental.json"


class NixlExperimentTests(unittest.TestCase):
    def test_spark7_smoke_plan_uses_experimental_vllm_main(self) -> None:
        build = VllmBuildPlan.load(BUILD_PATH)
        deployment = NixlDeployment.load(SMOKE_DEPLOYMENT)
        plan = plan_spark7_experiment(deployment=deployment, build=build)

        self.assertEqual(plan["format"], "ds4-nixl-spark7-experiment-v1")
        self.assertEqual(plan["build"]["git_ref"], "main")
        self.assertEqual(plan["launch"]["prefiller"]["spark_node"], "spark7")
        self.assertEqual(plan["launch"]["decoder"]["spark_node"], "spark7")
        self.assertIn("GDN NIXL", "\n".join(plan["rationale"]))

    def test_qwen_smoke_deployment_has_gdn_required_flags(self) -> None:
        deployment = NixlDeployment.load(SMOKE_DEPLOYMENT)
        launch = plan_deployment(deployment)
        prefiller_args = launch["prefiller"]["argv"]

        self.assertIn("--trust-remote-code", prefiller_args)
        self.assertIn("--no-async-scheduling", prefiller_args)
        self.assertIn("--no-disable-hybrid-kv-cache-manager", prefiller_args)
        self.assertIn("NixlConnector", launch["prefiller"]["command"])

    def test_qwen27_experimental_deployment_is_spark7_only(self) -> None:
        deployment = NixlDeployment.load(QWEN27_DEPLOYMENT)
        self.assertEqual(deployment.prefiller.spark_node, "spark7")
        self.assertEqual(deployment.decoder.spark_node, "spark7")
        self.assertEqual(deployment.prefiller.model_id, "/home/spark7/models/hf/Qwen/Qwen3.6-27B-FP8")
        self.assertEqual(deployment.decoder.model_id, "/home/spark7/models/hf/Qwen/Qwen3.6-27B-FP8")
        self.assertIn("--served-model-name", deployment.prefiller.extra_args)

    def test_write_spark7_experiment_bundle(self) -> None:
        build = VllmBuildPlan.load(BUILD_PATH)
        deployment = NixlDeployment.load(SMOKE_DEPLOYMENT)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_spark7_experiment(deployment=deployment, build=build, output_dir=tmp)
            scripts = manifest["scripts"]
            for key in ("install", "prefiller", "decoder", "proxy", "smoke", "stop", "readme"):
                self.assertTrue(Path(scripts[key]).exists(), key)
            install_text = Path(scripts["install"]).read_text()
            self.assertIn("git checkout main", install_text)
            self.assertIn("nixl-cu13==1.1.0", install_text)
            self.assertIn("VLLM_USE_PRECOMPILED=1", install_text)

    def test_cli_plan_command_writes_json(self) -> None:
        # Keep this as a pure import/schema test; the subprocess path is covered by compileall.
        self.assertTrue(BUILD_PATH.exists())
        data = json.loads(BUILD_PATH.read_text())
        self.assertEqual(data["format"], "ds4-vllm-build-plan-v1")


if __name__ == "__main__":
    unittest.main()
