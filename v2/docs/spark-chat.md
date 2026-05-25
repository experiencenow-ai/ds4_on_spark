# Spark chat CLI

`ds4-spark-chat` is a simple local chat interface for the DS4 Spark lanes.

It keeps full chat history on the Mac Studio, then submits each turn through
the v2 queue. The model call itself runs on the selected Spark through
`--runner spark`.

Example:

```bash
PYTHONPATH=src python3 -m ds4_chat.cli -m ds4v
PYTHONPATH=src python3 -m ds4_chat.cli -m qwen
PYTHONPATH=src python3 -m ds4_chat.cli -m ds4a
```

If Spark hostnames do not resolve from the Mac Studio, run
`python3 v2/scripts/print_spark_hosts.py` from the repo root and install the
generated entries into `/etc/hosts`.

Single question mode:

```bash
PYTHONPATH=src python3 -m ds4_chat.cli \
  -m ds4v \
  --allow-spark7-tools \
  --ask 'Check the planned Spark status command and explain what you would run.'
```

`--mode direct-vllm` keeps the old direct OpenAI-compatible behavior for
debugging a single endpoint, but queue mode is the default production path.

Tools available by default:

- `tool:spark.status`
- `tool:spark.transfer.plan`
- `tool:spark.transfer.run`
- `tool:web.fetch`
- basic `tool:ds4.*` utilities

`--allow-spark7-tools` grants access to `tool:spark7.command.run`, which can execute arbitrary shell commands on spark7 when the model passes `execute=true`. Without that flag, the chat loop denies spark7 tools.
