import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lane_claim_next.sh"


FAKE_GH = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]

def save():
    state_path.write_text(json.dumps(state, sort_keys=True))

def labels_for(issue):
    return issue.get("labels", [])

def issue_payload(num, issue):
    return {
        "number": int(num),
        "title": issue.get("title", ""),
        "state": issue.get("state", "OPEN"),
        "body": issue.get("body", ""),
        "labels": [{"name": label} for label in labels_for(issue)],
    }

def get_option(name, default=None):
    for i, arg in enumerate(args):
        if arg == name and (i + 1) < len(args):
            return args[i + 1]
    return default

if args[:2] == ["issue", "list"]:
    wanted_labels = []
    state_filter = get_option("--state")
    i = 0
    while i < len(args):
        if args[i] == "--label":
            wanted_labels.append(args[i + 1])
            i += 2
        else:
            i += 1
    out = []
    for num, issue in state["issues"].items():
        if state_filter == "open" and issue.get("state", "OPEN") != "OPEN":
            continue
        labels = set(labels_for(issue))
        if all(label in labels for label in wanted_labels):
            out.append(issue_payload(num, issue))
    print(json.dumps(out))
    sys.exit(0)

if args[:2] == ["issue", "view"]:
    num = args[2]
    issue = state["issues"][num]
    jq = get_option("--jq", "")
    payload = issue_payload(num, issue)
    if jq == ".body":
        print(payload["body"])
    elif jq == ".state":
        print(payload["state"])
    elif jq == ".title":
        print(payload["title"])
    elif "join" in jq:
        print(",".join(labels_for(issue)))
    else:
        print(json.dumps(payload))
    sys.exit(0)

if args[:2] == ["issue", "edit"]:
    num = args[2]
    labels = labels_for(state["issues"][num])
    state.setdefault("edits", []).append(num)
    i = 0
    while i < len(args):
        if args[i] == "--remove-label":
            label = args[i + 1]
            labels = [item for item in labels if item != label]
            i += 2
        elif args[i] == "--add-label":
            label = args[i + 1]
            if label not in labels:
                labels.append(label)
            i += 2
        else:
            i += 1
    state["issues"][num]["labels"] = labels
    save()
    sys.exit(0)

if args[:2] == ["issue", "comment"]:
    num = args[2]
    state.setdefault("comments", []).append(num)
    save()
    sys.exit(0)

print("unsupported fake gh call: " + " ".join(args), file=sys.stderr)
sys.exit(2)
"""


class LaneClaimNextTest(unittest.TestCase):
    def run_claim(self, issues):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            gh_path = Path(tmp) / "gh"
            state_path.write_text(json.dumps({"issues": issues}, sort_keys=True))
            gh_path.write_text(FAKE_GH)
            gh_path.chmod(0o755)
            env = os.environ.copy()
            env["FAKE_GH_STATE"] = str(state_path)
            env["GH_BIN"] = str(gh_path)
            env["REPO"] = "fixture/repo"
            proc = subprocess.run(
                ["bash", str(SCRIPT), "3"],
                cwd=str(ROOT),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            state = json.loads(state_path.read_text())
            return proc, state

    def test_skips_candidate_when_spark_is_reserved(self):
        proc, state = self.run_claim(
            {
                "201": {
                    "title": "in progress spark2",
                    "labels": ["track:1", "status:in-progress", "hw:spark-2"],
                },
                "202": {
                    "title": "spark2 candidate",
                    "labels": ["track:backlog", "status:queued", "prio:P0", "hw:spark-2"],
                },
                "203": {
                    "title": "no hardware candidate",
                    "labels": ["track:backlog", "status:queued", "prio:P0", "hw:none"],
                },
            }
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Reserved Sparks right now: [2]; free: 7 of 8", proc.stdout)
        self.assertIn("CLAIMED #203 no hardware candidate", proc.stdout)
        self.assertIn("track:backlog", state["issues"]["202"]["labels"])
        self.assertIn("track:3", state["issues"]["203"]["labels"])
        self.assertEqual(state["edits"], ["203"])

    def test_successful_claim_exits_before_second_candidate(self):
        proc, state = self.run_claim(
            {
                "301": {
                    "title": "first candidate",
                    "labels": ["track:backlog", "status:queued", "prio:P0", "hw:none"],
                },
                "302": {
                    "title": "second candidate",
                    "labels": ["track:backlog", "status:queued", "prio:P0", "hw:none"],
                },
            }
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("CLAIMED #301 first candidate", proc.stdout)
        self.assertNotIn("CLAIMED #302", proc.stdout)
        self.assertNotRegex(proc.stdout, r"\nnone\s*$")
        self.assertIn("track:3", state["issues"]["301"]["labels"])
        self.assertIn("track:backlog", state["issues"]["302"]["labels"])
        self.assertEqual(state["edits"], ["301"])


if __name__ == "__main__":
    unittest.main()
