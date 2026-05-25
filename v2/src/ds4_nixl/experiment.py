from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
from typing import Any

from .service import NixlDeployment, plan_deployment, write_launch_scripts

VLLM_BUILD_FORMAT = "ds4-vllm-build-plan-v1"
NIXL_EXPERIMENT_FORMAT = "ds4-nixl-spark7-experiment-v1"


@dataclass(frozen=True)
class VllmBuildPlan:
    build_id: str
    repo_url: str
    git_ref: str
    runtime_dir: str
    venv_dir: str
    install_mode: str
    python_bin: str
    force_reinstall_nixl_cu13: bool
    notes: tuple[str, ...]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "VllmBuildPlan":
        if data.get("format") != VLLM_BUILD_FORMAT:
            raise ValueError(f"unsupported vLLM build plan format: {data.get('format')!r}")
        build_id = str(data.get("build_id", "vllm_experimental"))
        repo_url = str(data.get("repo_url", "https://github.com/vllm-project/vllm.git"))
        git_ref = str(data.get("git_ref", "main"))
        runtime_dir = str(data.get("runtime_dir", f"/home/spark7/standard-runtimes/{build_id}"))
        venv_dir = str(data.get("venv_dir", f"{runtime_dir}/venv"))
        install_mode = str(data.get("install_mode", "editable_precompiled"))
        if install_mode not in {"editable_precompiled", "pip_git"}:
            raise ValueError(f"unsupported install_mode: {install_mode!r}")
        return VllmBuildPlan(
            build_id=build_id,
            repo_url=repo_url,
            git_ref=git_ref,
            runtime_dir=runtime_dir,
            venv_dir=venv_dir,
            install_mode=install_mode,
            python_bin=str(data.get("python_bin", "python3")),
            force_reinstall_nixl_cu13=bool(data.get("force_reinstall_nixl_cu13", True)),
            notes=tuple(str(item) for item in data.get("notes", [])),
        )

    @staticmethod
    def load(path: str | Path) -> "VllmBuildPlan":
        with Path(path).open("r", encoding="utf-8") as handle:
            return VllmBuildPlan.from_json(json.load(handle))


def plan_spark7_experiment(*, deployment: NixlDeployment, build: VllmBuildPlan) -> dict[str, Any]:
    launch_plan = plan_deployment(deployment)
    return {
        "format": NIXL_EXPERIMENT_FORMAT,
        "experiment_id": f"{deployment.deployment_id}__{build.build_id}",
        "deployment_id": deployment.deployment_id,
        "profile_id": deployment.profile_id,
        "build_id": build.build_id,
        "risk": "spark7_only_experimental",
        "rationale": [
            "Test a vLLM build containing merged GDN NIXL support without disturbing production lanes.",
            "Run a small GDN model smoke first; only attempt the heavy Qwen27 profile if memory allows.",
            "DSV4 NIXL remains important but needs spark4+spark5 live testing when those lanes are free.",
        ],
        "build": build_script_plan(build),
        "launch": launch_plan,
        "smoke": smoke_request_plan(deployment),
    }


def write_spark7_experiment(*, deployment: NixlDeployment, build: VllmBuildPlan, output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    launch_manifest = write_launch_scripts(deployment, root)
    install_script = root / "00_install_experimental_vllm.sh"
    install_script.write_text(_install_script_text(build), encoding="utf-8")
    install_script.chmod(0o755)
    smoke_script = root / "04_smoke_request.sh"
    smoke_script.write_text(_smoke_script_text(deployment), encoding="utf-8")
    smoke_script.chmod(0o755)
    stop_script = root / "05_stop_experiment.sh"
    stop_script.write_text(_stop_script_text(deployment), encoding="utf-8")
    stop_script.chmod(0o755)
    readme = root / "README.md"
    readme.write_text(_readme_text(deployment, build), encoding="utf-8")
    experiment = plan_spark7_experiment(deployment=deployment, build=build)
    manifest = {
        "format": "ds4-nixl-spark7-experiment-bundle-v1",
        "experiment": experiment,
        "scripts": {
            "install": str(install_script),
            "prefiller": launch_manifest["scripts"]["prefiller"],
            "decoder": launch_manifest["scripts"]["decoder"],
            "proxy": launch_manifest["scripts"]["proxy"],
            "smoke": str(smoke_script),
            "stop": str(stop_script),
            "readme": str(readme),
        },
    }
    (root / "spark7_experiment_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def build_script_plan(build: VllmBuildPlan) -> dict[str, Any]:
    return {
        "build_id": build.build_id,
        "repo_url": build.repo_url,
        "git_ref": build.git_ref,
        "runtime_dir": build.runtime_dir,
        "venv_dir": build.venv_dir,
        "install_mode": build.install_mode,
        "force_reinstall_nixl_cu13": build.force_reinstall_nixl_cu13,
        "notes": list(build.notes),
    }


def smoke_request_plan(deployment: NixlDeployment) -> dict[str, Any]:
    return {
        "proxy_url": f"http://{deployment.proxy_host}:{deployment.proxy_port}/v1/completions",
        "model": deployment.prefiller.model_id,
        "payload": {
            "model": deployment.prefiller.model_id,
            "prompt": "Return exactly the word ok.",
            "max_tokens": 4,
            "temperature": 0,
        },
    }


def _install_script_text(build: VllmBuildPlan) -> str:
    runtime = shlex.quote(build.runtime_dir)
    venv = shlex.quote(build.venv_dir)
    repo = shlex.quote(build.repo_url)
    ref = shlex.quote(build.git_ref)
    python_bin = shlex.quote(build.python_bin)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "echo '[ds4-nixl] installing experimental vLLM runtime'",
        f"mkdir -p {runtime}",
        f"if [ ! -d {runtime}/vllm/.git ]; then git clone {repo} {runtime}/vllm; fi",
        f"cd {runtime}/vllm",
        "git fetch --all --tags --prune",
        f"git checkout {ref}",
        "git rev-parse HEAD | tee ../vllm_commit.txt",
        f"{python_bin} -m venv {venv}",
        f"source {venv}/bin/activate",
        "python -m pip install --upgrade pip wheel setuptools ninja packaging",
        "python -m pip install --upgrade torch",
        "python -m pip install --upgrade nixl",
    ]
    if build.force_reinstall_nixl_cu13:
        lines.append("python -m pip install --force-reinstall nixl-cu13==1.1.0")
    if build.install_mode == "editable_precompiled":
        lines.extend(
            [
                "export VLLM_USE_PRECOMPILED=1",
                "python -m pip install -e . --no-build-isolation",
            ]
        )
    else:
        lines.append(f"python -m pip install --upgrade git+{build.repo_url}@{build.git_ref}")
    lines.extend(
        [
            "python - <<'PY'",
            "import importlib, shutil, subprocess, sys",
            "print('python', sys.executable)",
            "print('ninja', shutil.which('ninja'))",
            "print('vllm', shutil.which('vllm'))",
            "import torch; print('torch cuda', torch.version.cuda)",
            "import nixl; print('import nixl ok')",
            "import nixl_ep; print('import nixl_ep ok')",
            "subprocess.check_call(['vllm', '--version'])",
            "PY",
            "echo '[ds4-nixl] runtime ready'",
            "",
        ]
    )
    return "\n".join(lines)


def _smoke_script_text(deployment: NixlDeployment) -> str:
    proxy_url = f"http://{deployment.proxy_host}:{deployment.proxy_port}/v1/completions"
    model = deployment.prefiller.model_id
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"curl -sS -H 'content-type: application/json' {shlex.quote(proxy_url)} \\",
            "  -d " + shlex.quote(json.dumps({"model": model, "prompt": "Return exactly the word ok.", "max_tokens": 4, "temperature": 0})),
            "echo",
            "",
        ]
    )


def _stop_script_text(deployment: NixlDeployment) -> str:
    patterns = [
        str(deployment.prefiller.http_port),
        str(deployment.decoder.http_port),
        str(deployment.proxy_port),
        deployment.prefiller.model_id,
    ]
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "echo '[ds4-nixl] stopping experiment processes owned by this user'",
            "pkill -u \"$(id -u)\" -f " + shlex.quote("|".join(patterns)) + " || true",
            "",
        ]
    )


def _readme_text(deployment: NixlDeployment, build: VllmBuildPlan) -> str:
    return f"""# DS4 spark7 NIXL experiment bundle

This bundle is intentionally spark7-only. It installs an experimental vLLM runtime at:

```text
{build.runtime_dir}
```

The target vLLM ref is:

```text
{build.git_ref}
```

Run order:

```bash
./00_install_experimental_vllm.sh
source {build.venv_dir}/bin/activate
./start_prefiller.sh > prefiller.log 2>&1 &
./start_decoder.sh > decoder.log 2>&1 &
./start_proxy.sh > proxy.log 2>&1 &
./04_smoke_request.sh
```

Deployment:

```text
profile: {deployment.profile_id}
model:   {deployment.prefiller.model_id}
prefill: {deployment.prefiller.host}:{deployment.prefiller.http_port}
decode:  {deployment.decoder.host}:{deployment.decoder.http_port}
proxy:   {deployment.proxy_host}:{deployment.proxy_port}
```

Use this first with the small GDN smoke profile. Only run the heavy Qwen27 deployment after the small smoke confirms that the experimental vLLM build contains working GDN NIXL support.

Stop:

```bash
./05_stop_experiment.sh
```
"""
