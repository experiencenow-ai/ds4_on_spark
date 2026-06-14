#!/usr/bin/env python3
"""Export dashboard model layer partitions from a repo checkout."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    from . import spark_telemetry_dashboard as dashboard
except ImportError:
    import spark_telemetry_dashboard as dashboard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--out", required=True)
    return(parser.parse_args())


def main() -> int:
    args = parse_args()
    dashboard.REPO_ROOT_OVERRIDE = str(Path(args.repo_root).expanduser().resolve())
    dashboard.MODEL_LAYER_PARTITIONS_JSON_OVERRIDE = "/nonexistent/ds4-no-installed-partitions.json"
    dashboard.MODEL_LAYER_PARTITIONS = None
    partitions = dashboard.load_model_layer_partitions()
    payload = {
        "format": "ds4-telemetry-model-layer-partitions-v1",
        "repo_root": dashboard.REPO_ROOT_OVERRIDE,
        "model_layer_partitions": partitions,
    }
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True,exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload,indent=2,sort_keys=True) + "\n",encoding="utf-8")
    os.replace(tmp_path,out_path)
    print("wrote %s model layer partitions to %s" % (len(partitions),out_path),flush=True)
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
