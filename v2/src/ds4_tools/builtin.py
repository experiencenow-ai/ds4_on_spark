from __future__ import annotations

from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from urllib import request as urlrequest

from .cpu_batch import CpuBatchService


CPU = CpuBatchService()


def json_validate(arguments: dict[str, Any]) -> dict[str, Any]:
    text = str(arguments.get("text", ""))
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": str(exc), "line": exc.lineno, "column": exc.colno}
    return {"ok": True, "type": type(value).__name__, "value": value}


def sha256_text(arguments: dict[str, Any]) -> dict[str, Any]:
    text = str(arguments.get("text", ""))
    return {"ok": True, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def text_metrics(arguments: dict[str, Any]) -> dict[str, Any]:
    text = str(arguments.get("text", ""))
    lines = text.splitlines()
    return {"ok": True, "bytes_utf8": len(text.encode("utf-8")), "characters": len(text), "lines": len(lines), "nonempty_lines": sum(1 for line in lines if line.strip())}


def regex_match(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **CPU.service_regex_match(arguments)}


def diff_stats(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **CPU.service_diff_stats(arguments)}


def cpu_services(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **CPU.status()}


def cpu_batch(arguments: dict[str, Any]) -> dict[str, Any]:
    return CPU.run_batch(arguments)


def web_fetch(arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments.get("url", ""))
    mode = str(arguments.get("mode", "auto"))
    timeout_s = int(arguments.get("timeout_s", 30))
    wait_ms = int(arguments.get("wait_ms", 1000))
    max_text_chars = int(arguments.get("max_text_chars", 20000))
    if not url.startswith(("http://", "https://")):
        raise ValueError("web.fetch url must start with http:// or https://")
    if mode not in {"auto", "text", "rendered"}:
        raise ValueError("web.fetch mode must be auto, text, or rendered")
    if mode in {"auto", "rendered"}:
        rendered = _try_playwright_fetch(url=url, timeout_s=timeout_s, wait_ms=wait_ms, max_text_chars=max_text_chars)
        if rendered.get("ok") or mode == "rendered":
            return rendered
    return _urllib_fetch(url=url, timeout_s=timeout_s, max_text_chars=max_text_chars)


def spark_status(arguments: dict[str, Any]) -> dict[str, Any]:
    node = str(arguments.get("node", "all"))
    execute = bool(arguments.get("execute", False))
    timeout_s = int(arguments.get("timeout_s", 10))
    nodes = [f"spark{i}" for i in range(8)] if node == "all" else [node]
    _validate_spark_nodes(nodes)
    argv_by_node = {spark: ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", spark, "hostname; uptime"] for spark in nodes}
    if not execute:
        return {"ok": True, "execute": False, "planned": argv_by_node}
    results: dict[str, Any] = {}
    for spark, argv in argv_by_node.items():
        completed = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_s, check=False)
        results[spark] = {"ok": completed.returncode == 0, "returncode": completed.returncode, "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-2000:]}
    return {"ok": all(item["ok"] for item in results.values()), "execute": True, "results": results}


def spark7_run_command(arguments: dict[str, Any]) -> dict[str, Any]:
    command = str(arguments.get("command", ""))
    execute = bool(arguments.get("execute", False))
    timeout_s = int(arguments.get("timeout_s", 120))
    if not command.strip():
        raise ValueError("spark7 command cannot be empty")
    argv = ["ssh", "-o", "BatchMode=yes", "spark7", "bash", "-lc", command]
    if not execute:
        return {"ok": True, "execute": False, "planned": {"argv": argv, "node": "spark7"}}
    completed = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_s, check=False)
    return {"ok": completed.returncode == 0, "execute": True, "node": "spark7", "returncode": completed.returncode, "stdout_tail": completed.stdout[-8000:], "stderr_tail": completed.stderr[-8000:]}


def transfer_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    from ds4_transfer.service import TransferRequest, TransferTopology, plan_transfer
    topology = TransferTopology.load(Path(str(arguments.get("topology", "profiles/transfer/spark_200g.json"))))
    payload = {"format": "ds4-transfer-request-v1", "source_node": arguments["source_node"], "source_path": arguments["source_path"], "destination_node": arguments["destination_node"], "destination_path": arguments["destination_path"], "recursive": bool(arguments.get("recursive", True)), "delete_extra": bool(arguments.get("delete_extra", False)), "dry_run": True}
    return {"ok": True, "plan": plan_transfer(topology, TransferRequest.from_json(payload))}


def transfer_run(arguments: dict[str, Any]) -> dict[str, Any]:
    from ds4_transfer.service import TransferRequest, TransferTopology, run_transfer
    topology = TransferTopology.load(Path(str(arguments.get("topology", "profiles/transfer/spark_200g.json"))))
    payload = {"format": "ds4-transfer-request-v1", "source_node": arguments["source_node"], "source_path": arguments["source_path"], "destination_node": arguments["destination_node"], "destination_path": arguments["destination_path"], "recursive": bool(arguments.get("recursive", True)), "delete_extra": bool(arguments.get("delete_extra", False)), "dry_run": bool(arguments.get("dry_run", True))}
    return {"ok": True, "transfer": run_transfer(topology, TransferRequest.from_json(payload), timeout_s=int(arguments.get("timeout_s", 3600)), dry_run=bool(arguments.get("dry_run", True)))}


def kvcache_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    from ds4_kvcache.service import KvCacheDeployment, plan_deployment
    deployment = KvCacheDeployment.load(Path(str(arguments.get("deployment", "profiles/kv_cache/dsv4_spark45_hma_cpu_offload.json"))))
    return {"ok": True, "plan": plan_deployment(deployment)}


def hma_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    from ds4_hma.service import Dsv4HmaDeployment, plan_deployment
    deployment = Dsv4HmaDeployment.load(Path(str(arguments.get("deployment", "profiles/hma/dsv4_hma_persistent.json"))))
    return {"ok": True, "plan": plan_deployment(deployment)}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            attr_map = {name: value or "" for name, value in attrs}
            href = attr_map.get("href", "")
            if href:
                self.links.append({"href": href, "text": ""})

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._skip_depth == 0:
            self.text_parts.append(text)

    def result(self, *, max_text_chars: int) -> dict[str, Any]:
        text = "\n".join(self.text_parts)
        return {"title": " ".join(self.title_parts)[:500], "text": text[:max_text_chars], "text_truncated": len(text) > max_text_chars, "links": self.links[:100]}


def _urllib_fetch(*, url: str, timeout_s: int, max_text_chars: int) -> dict[str, Any]:
    req = urlrequest.Request(url, headers={"user-agent": "ds4-tools-web-fetch/1.0"})
    with urlrequest.urlopen(req, timeout=timeout_s) as response:
        body = response.read()
        final_url = response.geturl()
        status = getattr(response, "status", 200)
        content_type = response.headers.get("content-type", "")
    html = body.decode("utf-8", errors="replace")
    extractor = _TextExtractor()
    extractor.feed(html)
    parsed = extractor.result(max_text_chars=max_text_chars)
    parsed.update({"ok": True, "mode": "text", "url": url, "final_url": final_url, "status": status, "content_type": content_type, "html_sha256": hashlib.sha256(body).hexdigest()})
    return parsed


def _try_playwright_fetch(*, url: str, timeout_s: int, wait_ms: int, max_text_chars: int) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {"ok": False, "mode": "rendered", "error": f"playwright unavailable: {exc}", "install_hint": "pip install '.[web]' && python -m playwright install chromium"}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
                if wait_ms > 0:
                    page.wait_for_timeout(wait_ms)
                title = page.title()
                text = page.locator("body").inner_text(timeout=timeout_s * 1000)
                links = page.locator("a").evaluate_all("els => els.slice(0, 100).map(a => ({href: a.href, text: (a.innerText || '').slice(0, 200)}))")
                html = page.content()
                return {"ok": True, "mode": "rendered", "url": url, "final_url": page.url, "status": None, "title": title, "text": text[:max_text_chars], "text_truncated": len(text) > max_text_chars, "links": links, "html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest()}
            finally:
                browser.close()
    except Exception as exc:
        return {"ok": False, "mode": "rendered", "error": str(exc), "fallback_available": True}


def _validate_spark_nodes(nodes: list[str]) -> None:
    allowed = {f"spark{i}" for i in range(8)}
    invalid = [node for node in nodes if node not in allowed]
    if invalid:
        raise ValueError(f"invalid spark node(s): {invalid}")
