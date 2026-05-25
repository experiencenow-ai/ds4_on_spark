# Web tools

`tool:web.fetch` is the default web-access tool.

It uses Playwright rendering when `mode=rendered` or `mode=auto` can use Playwright, and falls back to a simple urllib HTML fetch in `mode=text`. This keeps the tool deterministic and local-first while still supporting JavaScript-rendered pages when the optional browser dependency is installed.

Install browser support:

```bash
pip install '.[web]'
python -m playwright install chromium
```

Invoke:

```bash
PYTHONPATH=src python3 -m ds4_tools.cli invoke \
  --registry tools/registry.jsonl \
  --tool-id tool:web.fetch \
  --arguments '{"url":"https://example.com","mode":"rendered","max_text_chars":12000}'
```

Playwright is the first implementation because it is a stable deterministic browser automation layer. Higher-level browser-agent systems can be added later as separate tool atoms, but the base tool should not require a cloud browser service or another LLM.
