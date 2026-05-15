#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import statistics
import struct
import time
from pathlib import Path


HDR = struct.Struct("!QQ")


def parse_int_list(text: str) -> list[int]:
	return [int(item.strip()) for item in text.replace(" ", ",").split(",") if item.strip()]


def recvall(conn: socket.socket, size: int) -> bytes:
	buf = bytearray()
	while len(buf) < size:
		chunk = conn.recv(size - len(buf))
		if not chunk:
			raise ConnectionError("socket closed")
		buf.extend(chunk)
	return bytes(buf)


def server(args: argparse.Namespace) -> int:
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		sock.bind((args.bind, args.port))
		sock.listen(1)
		print(json.dumps({"ok": True, "server": f"{args.bind}:{args.port}", "event": "listening"}), flush=True)
		conn, addr = sock.accept()
		with conn:
			print(json.dumps({"ok": True, "client": addr[0], "event": "accepted"}), flush=True)
			while True:
				header = recvall(conn, HDR.size)
				byte_count, seq = HDR.unpack(header)
				if byte_count == 0:
					break
				if byte_count > args.max_bytes:
					raise ValueError("payload exceeds --max-bytes")
				recvall(conn, int(byte_count))
				conn.sendall(HDR.pack(0, seq))
	return 0


def percentile(values: list[float], q: float) -> float:
	if len(values) == 0:
		return 0.0
	if len(values) == 1:
		return values[0]
	index = int(round((len(values) - 1) * q))
	return sorted(values)[index]


def run_one_payload(sock: socket.socket, payload: bytes, seq: int) -> float:
	start_ns = time.perf_counter_ns()
	sock.sendall(HDR.pack(len(payload), seq))
	sock.sendall(payload)
	ack = recvall(sock, HDR.size)
	_, ack_seq = HDR.unpack(ack)
	if ack_seq != seq:
		raise RuntimeError("ack sequence mismatch")
	return (time.perf_counter_ns() - start_ns) / 1_000_000.0


def client(args: argparse.Namespace) -> int:
	rows = []
	batches = parse_int_list(args.batch_sizes)
	if args.row_bytes <= 0 and args.payload_bytes <= 0:
		raise SystemExit("--row-bytes or --payload-bytes is required")
	with socket.create_connection((args.host, args.port), timeout=args.connect_timeout_s) as sock:
		sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
		seq = 1
		for batch in batches:
			byte_count = args.payload_bytes if args.payload_bytes > 0 else args.row_bytes * batch
			payload = bytes((i % 251 for i in range(byte_count)))
			for _ in range(args.warmup):
				run_one_payload(sock, payload, seq)
				seq += 1
			times = []
			for _ in range(args.iters):
				times.append(run_one_payload(sock, payload, seq))
				seq += 1
			p50_ms = statistics.median(times)
			p95_ms = percentile(times, 0.95)
			gbps = (byte_count / 1_000_000_000.0) / (p50_ms / 1000.0)
			rows.append({
				"batch": batch,
				"byte_count": byte_count,
				"iters": args.iters,
				"p50_ms": p50_ms,
				"p95_ms": p95_ms,
				"bandwidth_GB_s_p50": gbps,
			})
		sock.sendall(HDR.pack(0, seq))
	payload = {"ok": True, "rows": rows}
	if args.json_out:
		Path(args.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	print(json.dumps(payload, indent=2, sort_keys=True))
	return 0


def main() -> int:
	parser = argparse.ArgumentParser(description="Measure binary activation-sized transfers between Spark stages.")
	sub = parser.add_subparsers(dest="cmd", required=True)
	sp = sub.add_parser("server")
	sp.add_argument("--bind", default="0.0.0.0")
	sp.add_argument("--port", type=int, default=18551)
	sp.add_argument("--max-bytes", type=int, default=2 * 1024 * 1024 * 1024)
	cp = sub.add_parser("client")
	cp.add_argument("--host", required=True)
	cp.add_argument("--port", type=int, default=18551)
	cp.add_argument("--batch-sizes", default="32,64,128,256,512,1024")
	cp.add_argument("--row-bytes", type=int, default=0)
	cp.add_argument("--payload-bytes", type=int, default=0)
	cp.add_argument("--warmup", type=int, default=3)
	cp.add_argument("--iters", type=int, default=30)
	cp.add_argument("--connect-timeout-s", type=float, default=10.0)
	cp.add_argument("--json-out", default="")
	args = parser.parse_args()
	if args.cmd == "server":
		return server(args)
	return client(args)


if __name__ == "__main__":
	raise SystemExit(main())
