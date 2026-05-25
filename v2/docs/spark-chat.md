# Spark chat CLI

`ds4-spark-chat` is a simple local chat interface for the DSV4/vLLM/MTP lane.

It intentionally brute-forces the full chat history as OpenAI-compatible chat messages. This is enough for Mac Studio usage and keeps the first version easy to debug.

Example:

```bash
export DS4_VLLM_MTP_BASE_URL=http://spark4:8000
PYTHONPATH=src python3 -m ds4_chat.cli \
  --registry tools/registry.jsonl \
  --history ~/.ds4_spark_chat_history.json \
  --allow-spark7-tools
```

Single question mode:

```bash
PYTHONPATH=src python3 -m ds4_chat.cli \
  --allow-spark7-tools \
  --ask 'Check the planned Spark status command and explain what you would run.'
```

Tools available by default:

- `tool:spark.status`
- `tool:spark.transfer.plan`
- `tool:spark.transfer.run`
- `tool:web.fetch`
- basic `tool:ds4.*` utilities

`--allow-spark7-tools` grants access to `tool:spark7.command.run`, which can execute arbitrary shell commands on spark7 when the model passes `execute=true`. Without that flag, the chat loop denies spark7 tools.
