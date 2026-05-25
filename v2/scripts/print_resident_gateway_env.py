from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"
PROFILES = ROOT / "profiles" / "models"

RESIDENT_TUNING = {
    "qwen3_6_27b_fp8_efficient_v1": {"gpu_memory_utilization": "0.44", "max_num_seqs": "32", "max_num_batched_tokens": "16384"},
    "qwen3_6_35b_a3b_fp8_fastest_v1": {"gpu_memory_utilization": "0.28", "max_num_seqs": "64", "max_num_batched_tokens": "16384"},
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Print model-gateway.env values for one Spark node.")
    parser.add_argument("--node", required=True)
    parser.add_argument("--topology", default=str(TOPOLOGY))
    parser.add_argument("--profiles-dir", default=str(PROFILES))
    parser.add_argument("--resident-base-port", type=int, default=18100)
    args = parser.parse_args()
    topology = json.loads(Path(args.topology).read_text(encoding="utf-8"))
    node = _find_node(topology, args.node)
    grouped_profiles = set((topology.get("routing_policy") or {}).get("profile_node_groups", {}))
    profile_ids = [] if node.get("dynamic_load") else list(node.get("resident_profiles", []))
    profiles = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in Path(args.profiles_dir).glob("*.json")}
    specs = []
    for idx, profile_id in enumerate(profile_ids):
        if profile_id in grouped_profiles:
            continue
        profile = profiles[profile_id.removesuffix("_v1")] if profile_id.removesuffix("_v1") in profiles else _profile_by_id(profiles, profile_id)
        if str(profile.get("backend", "")).startswith("vllm"):
            spec = {"model": profile["model_id"], "port": args.resident_base_port + idx}
            if profile_id in RESIDENT_TUNING:
                spec["tuning"] = RESIDENT_TUNING[profile_id]
            specs.append(spec)
    print("FRONT_HOST=127.0.0.1")
    print("FRONT_PORT=8000")
    print("BACKEND_HOST=127.0.0.1")
    print("BACKEND_PORT=18000")
    print(f"DS4_RESIDENT_BACKEND_BASE_PORT={args.resident_base_port}")
    print("DS4_RESIDENT_START=1")
    print("START_TIMEOUT=3600")
    print("IDLE_TIMEOUT=1800")
    print("DS4_RESIDENT_MODELS_JSON=" + json.dumps(specs, separators=(",", ":")))
    return 0


def _find_node(topology: dict, node_id: str) -> dict:
    for node in topology.get("nodes", []):
        if node.get("node_id") == node_id:
            return node
    raise SystemExit(f"unknown node in topology: {node_id}")


def _profile_by_id(profiles: dict[str, dict], profile_id: str) -> dict:
    for profile in profiles.values():
        if profile.get("profile_id") == profile_id:
            return profile
    raise SystemExit(f"unknown profile id: {profile_id}")


if __name__ == "__main__":
    raise SystemExit(main())
