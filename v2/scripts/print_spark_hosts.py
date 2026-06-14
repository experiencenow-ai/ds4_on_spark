from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


DEFAULT_TOPOLOGY = Path(__file__).resolve().parents[1] / "profiles" / "transfer" / "spark_200g.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print /etc/hosts entries from SSH Spark aliases.")
    parser.add_argument("--topology", default=str(DEFAULT_TOPOLOGY))
    parser.add_argument("nodes", nargs="*")
    args = parser.parse_args()
    nodes = args.nodes if args.nodes else _load_topology_nodes(Path(args.topology))
    print("# DS4 Spark aliases generated from ssh -G")
    for node in nodes:
        hostname = _ssh_hostname(node)
        aliases = f"{node} spark6-wifi" if node == "spark6" else node
        print(f"{hostname} {aliases}")
    return 0


def _load_topology_nodes(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as handle:
        topology = json.load(handle)
    nodes = [str(node.get("node_id")) for node in topology.get("nodes", []) if node.get("node_id")]
    if not nodes:
        raise SystemExit(f"no Spark nodes found in topology: {path}")
    return nodes


def _ssh_hostname(node: str) -> str:
    completed = subprocess.run(["ssh", "-G", node], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"ssh -G {node} failed: {completed.stderr.strip()}")
    for line in completed.stdout.splitlines():
        if line.startswith("hostname "):
            return line.split(None, 1)[1]
    raise SystemExit(f"ssh -G {node} did not report a hostname")


if __name__ == "__main__":
    raise SystemExit(main())
