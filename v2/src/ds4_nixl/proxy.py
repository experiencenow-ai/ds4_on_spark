from __future__ import annotations

import argparse
import itertools
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.prefill_clients = _client_pool(ARGUMENTS.prefiller_instances)
    app.state.decode_clients = _client_pool(ARGUMENTS.decoder_instances)
    app.state.prefill_iterator = itertools.cycle(range(len(app.state.prefill_clients)))
    app.state.decode_iterator = itertools.cycle(range(len(app.state.decode_clients)))
    try:
        yield
    finally:
        for item in app.state.prefill_clients + app.state.decode_clients:
            await item["client"].aclose()


def _client_pool(instances: list[tuple[str, int]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, (host, port) in enumerate(instances):
        items.append(
            {
                "client": httpx.AsyncClient(
                    timeout=None,
                    base_url=f"http://{host}:{port}/v1",
                    limits=httpx.Limits(max_connections=None, max_keepalive_connections=None),
                ),
                "host": host,
                "port": port,
                "id": index,
            }
        )
    return items


def _next_client(app: FastAPI, service_type: str) -> dict[str, Any]:
    if service_type == "prefill":
        return app.state.prefill_clients[next(app.state.prefill_iterator)]
    if service_type == "decode":
        return app.state.decode_clients[next(app.state.decode_iterator)]
    raise ValueError(f"unknown service_type: {service_type}")


async def _prefill(client_info: dict[str, Any], endpoint: str, request_data: dict[str, Any], request_id: str) -> dict[str, Any]:
    data = dict(request_data)
    data["kv_transfer_params"] = {
        "do_remote_decode": True,
        "do_remote_prefill": False,
        "remote_engine_id": None,
        "remote_block_ids": None,
        "remote_host": None,
        "remote_port": None,
    }
    data["stream"] = False
    data["max_tokens"] = 1
    if "max_completion_tokens" in data:
        data["max_completion_tokens"] = 1
    data.pop("stream_options", None)
    data.pop("min_tokens", None)
    data.pop("min_completion_tokens", None)
    response = await client_info["client"].post(endpoint, json=data, headers=_headers(request_id))
    response.raise_for_status()
    try:
        return response.json()
    finally:
        await response.aclose()


async def _decode_stream(client_info: dict[str, Any], endpoint: str, request_data: dict[str, Any], request_id: str) -> AsyncIterator[bytes]:
    async with client_info["client"].stream("POST", endpoint, json=request_data, headers=_headers(request_id)) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            yield chunk


async def _handle(endpoint: str, request: Request) -> StreamingResponse:
    request_data = await request.json()
    request_id = str(uuid.uuid4())
    prefill_client = _next_client(request.app, "prefill")
    decode_client = _next_client(request.app, "decode")
    prefill_response = await _prefill(prefill_client, endpoint, request_data, request_id)
    kv_transfer_params = prefill_response.get("kv_transfer_params")
    if isinstance(kv_transfer_params, dict) and kv_transfer_params:
        request_data["kv_transfer_params"] = kv_transfer_params
    LOGGER.debug("NIXL proxy %s -> %s", prefill_client, decode_client)

    async def generate() -> AsyncIterator[bytes]:
        async for chunk in _decode_stream(decode_client, endpoint, request_data, request_id):
            yield chunk

    return StreamingResponse(generate(), media_type="application/json")


def _headers(request_id: str) -> dict[str, str]:
    headers = {"X-Request-Id": request_id}
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


app = FastAPI(lifespan=lifespan)


@app.post("/v1/completions")
async def handle_completions(request: Request) -> StreamingResponse:
    return await _handle("/completions", request)


@app.post("/v1/chat/completions")
async def handle_chat_completions(request: Request) -> StreamingResponse:
    return await _handle("/chat/completions", request)


@app.get("/healthcheck")
async def healthcheck() -> dict[str, Any]:
    return {"status": "ok", "prefill_instances": len(app.state.prefill_clients), "decode_instances": len(app.state.decode_clients)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8192)
    parser.add_argument("--prefiller-hosts", "--prefiller-host", nargs="+", default=["127.0.0.1"])
    parser.add_argument("--prefiller-ports", "--prefiller-port", type=int, nargs="+", default=[8110])
    parser.add_argument("--decoder-hosts", "--decoder-host", nargs="+", default=["127.0.0.1"])
    parser.add_argument("--decoder-ports", "--decoder-port", type=int, nargs="+", default=[8120])
    args = parser.parse_args(argv)
    if len(args.prefiller_hosts) != len(args.prefiller_ports):
        raise ValueError("Number of prefiller hosts must match number of prefiller ports")
    if len(args.decoder_hosts) != len(args.decoder_ports):
        raise ValueError("Number of decoder hosts must match number of decoder ports")
    args.prefiller_instances = list(zip(args.prefiller_hosts, args.prefiller_ports))
    args.decoder_instances = list(zip(args.decoder_hosts, args.decoder_ports))
    return args


ARGUMENTS = parse_args([])


def main(argv: list[str] | None = None) -> None:
    global ARGUMENTS
    ARGUMENTS = parse_args(argv)
    import uvicorn

    uvicorn.run(app, host=ARGUMENTS.host, port=ARGUMENTS.port)


if __name__ == "__main__":
    main()
