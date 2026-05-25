from __future__ import annotations

import argparse
import subprocess


DEFAULT_NODES = ("spark0", "spark1", "spark2", "spark3", "spark4", "spark5", "spark6", "spark7")


def main() -> int:
    parser = argparse.ArgumentParser(description="Print /etc/hosts entries from SSH Spark aliases.")
    parser.add_argument("nodes", nargs="*", default=list(DEFAULT_NODES))
    args = parser.parse_args()
    print("# DS4 Spark aliases generated from ssh -G")
    for node in args.nodes:
        hostname = _ssh_hostname(node)
        aliases = f"{node} spark6-wifi" if node == "spark6" else node
        print(f"{hostname} {aliases}")
    return 0


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
