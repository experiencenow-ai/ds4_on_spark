#!/usr/bin/env bash
set -euo pipefail
/usr/bin/python3 -c 'import json, os; payload = json.loads(os.environ["DS4_TOOL_ARGUMENTS_JSON"]); print(json.dumps({"ok": True, "echo": payload}, sort_keys=True))'
