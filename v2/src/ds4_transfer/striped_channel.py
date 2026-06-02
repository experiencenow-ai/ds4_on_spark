from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import socket
import sys
import time


DEFAULT_CHUNK_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class StripeRange:
    index: int
    begin: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.begin


def stripe_ranges(size: int, stripe_count: int) -> list[StripeRange]:
    if size < 0:
        raise ValueError("size must be non-negative")
    if stripe_count < 1:
        raise ValueError("stripe_count must be positive")
    stripe_count = min(stripe_count, max(size, 1))
    base = size // stripe_count
    rem = size % stripe_count
    ranges: list[StripeRange] = []
    begin = 0
    for index in range(stripe_count):
        part = base + (1 if index < rem else 0)
        end = begin + part
        ranges.append(StripeRange(index=index, begin=begin, end=end))
        begin = end
    return ranges


def send_file_striped(
    *,
    source_path: str,
    destination_ip: str,
    port_base: int,
    stripe_count: int,
    source_ip: str | None,
    chunk_bytes: int,
    timeout_s: float,
    socket_buffer_bytes: int,
) -> dict[str, object]:
    path = Path(source_path)
    size = path.stat().st_size
    ranges = stripe_ranges(size, stripe_count)
    started = time.time()
    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        futures = [
            pool.submit(
                _send_stripe,
                path,
                destination_ip,
                port_base + item.index,
                item,
                source_ip,
                chunk_bytes,
                timeout_s,
                socket_buffer_bytes,
            )
            for item in ranges
        ]
        for future in as_completed(futures):
            future.result()
    duration = max(time.time() - started, 0.001)
    return {
        "ok": True,
        "method": "ds4_striped_tcp_file_v1",
        "direction": "send",
        "bytes": size,
        "stripes": len(ranges),
        "duration_s": round(duration, 6),
        "gbit_s": round(size * 8 / duration / 1_000_000_000, 6),
    }


def receive_file_striped(
    *,
    output_path: str,
    bind_ip: str,
    port_base: int,
    stripe_count: int,
    size: int,
    chunk_bytes: int,
    timeout_s: float,
    socket_buffer_bytes: int,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    path, tmp, ranges = _prepare_receive_file(output_path, size, stripe_count)
    started = time.time()
    _receive_stripe_ranges(
        tmp,
        bind_ip,
        port_base,
        ranges,
        chunk_bytes,
        timeout_s,
        socket_buffer_bytes,
    )
    _verify_receive_digest(tmp, output_path, expected_sha256)
    os.replace(tmp, path)
    return _transfer_result("recv", size, len(ranges), started)


def _prepare_receive_file(
    output_path: str,
    size: int,
    stripe_count: int,
) -> tuple[Path, Path, list[StripeRange]]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".ds4stripe")
    ranges = stripe_ranges(size, stripe_count)
    with tmp.open("wb") as handle:
        handle.truncate(size)
    return path, tmp, ranges


def _receive_stripe_ranges(
    tmp: Path,
    bind_ip: str,
    port_base: int,
    ranges: list[StripeRange],
    chunk_bytes: int,
    timeout_s: float,
    socket_buffer_bytes: int,
) -> None:
    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        futures = [
            pool.submit(
                _receive_stripe,
                tmp,
                bind_ip,
                port_base + item.index,
                item,
                chunk_bytes,
                timeout_s,
                socket_buffer_bytes,
            )
            for item in ranges
        ]
        for future in as_completed(futures):
            future.result()


def _verify_receive_digest(
    tmp: Path,
    output_path: str,
    expected_sha256: str | None,
) -> None:
    if not expected_sha256:
        return
    digest = file_sha256(tmp)
    if digest.lower() == expected_sha256.lower().removeprefix("sha256:"):
        return
    tmp.unlink(missing_ok=True)
    raise RuntimeError(
        f"sha256 mismatch for {output_path}: got {digest}, expected {expected_sha256}"
    )


def _transfer_result(
    direction: str,
    size: int,
    stripe_count: int,
    started: float,
) -> dict[str, object]:
    duration = max(time.time() - started, 0.001)
    return {
        "ok": True,
        "method": "ds4_striped_tcp_file_v1",
        "direction": direction,
        "bytes": size,
        "stripes": stripe_count,
        "duration_s": round(duration, 6),
        "gbit_s": round(size * 8 / duration / 1_000_000_000, 6),
    }


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            data = handle.read(DEFAULT_CHUNK_BYTES)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def _configure_socket(sock: socket.socket, socket_buffer_bytes: int) -> None:
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    if socket_buffer_bytes > 0:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, socket_buffer_bytes)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, socket_buffer_bytes)
        except OSError:
            pass


def _send_stripe(
    path: Path,
    destination_ip: str,
    port: int,
    item: StripeRange,
    source_ip: str | None,
    chunk_bytes: int,
    timeout_s: float,
    socket_buffer_bytes: int,
) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                _configure_socket(sock, socket_buffer_bytes)
                sock.settimeout(min(10.0, max(1.0, deadline - time.monotonic())))
                if source_ip:
                    sock.bind((source_ip, 0))
                sock.connect((destination_ip, port))
                with path.open("rb", buffering=0) as handle:
                    handle.seek(item.begin)
                    remaining = item.size
                    while remaining > 0:
                        block = handle.read(min(chunk_bytes, remaining))
                        if not block:
                            raise EOFError(f"short read from {path}")
                        sock.sendall(block)
                        remaining -= len(block)
                try:
                    sock.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                return
        except Exception as exc:  # pragma: no cover - depends on remote timing
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError(f"send stripe {item.index} failed: {last_error}")


def _receive_stripe(
    path: Path,
    bind_ip: str,
    port: int,
    item: StripeRange,
    chunk_bytes: int,
    timeout_s: float,
    socket_buffer_bytes: int,
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        _configure_socket(listener, socket_buffer_bytes)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((bind_ip, port))
        listener.listen(1)
        listener.settimeout(timeout_s)
        conn, _ = listener.accept()
        with conn:
            _configure_socket(conn, socket_buffer_bytes)
            conn.settimeout(timeout_s)
            fd = os.open(path, os.O_RDWR)
            try:
                offset = item.begin
                remaining = item.size
                while remaining > 0:
                    data = conn.recv(min(chunk_bytes, remaining))
                    if not data:
                        raise EOFError(
                            f"stripe {item.index} ended early with {remaining} bytes remaining"
                        )
                    os.pwrite(fd, data, offset)
                    offset += len(data)
                    remaining -= len(data)
            finally:
                os.close(fd)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ds4-striped-channel")
    sub = parser.add_subparsers(dest="cmd", required=True)
    recv = sub.add_parser("recv-file")
    recv.add_argument("--bind-ip", required=True)
    recv.add_argument("--port-base", type=int, required=True)
    recv.add_argument("--stripes", type=int, required=True)
    recv.add_argument("--size", type=int, required=True)
    recv.add_argument("--output", required=True)
    recv.add_argument("--chunk-bytes", type=int, default=DEFAULT_CHUNK_BYTES)
    recv.add_argument("--timeout-s", type=float, default=3600.0)
    recv.add_argument("--socket-buffer-bytes", type=int, default=16 * 1024 * 1024)
    recv.add_argument("--expected-sha256")

    send = sub.add_parser("send-file")
    send.add_argument("--source", required=True)
    send.add_argument("--destination-ip", required=True)
    send.add_argument("--source-ip")
    send.add_argument("--port-base", type=int, required=True)
    send.add_argument("--stripes", type=int, required=True)
    send.add_argument("--chunk-bytes", type=int, default=DEFAULT_CHUNK_BYTES)
    send.add_argument("--timeout-s", type=float, default=3600.0)
    send.add_argument("--socket-buffer-bytes", type=int, default=16 * 1024 * 1024)
    return parser


def _run_recv_file_args(args: argparse.Namespace) -> dict[str, object]:
    return receive_file_striped(
        output_path=args.output,
        bind_ip=args.bind_ip,
        port_base=args.port_base,
        stripe_count=args.stripes,
        size=args.size,
        chunk_bytes=args.chunk_bytes,
        timeout_s=args.timeout_s,
        socket_buffer_bytes=args.socket_buffer_bytes,
        expected_sha256=args.expected_sha256,
    )


def _run_send_file_args(args: argparse.Namespace) -> dict[str, object]:
    return send_file_striped(
        source_path=args.source,
        destination_ip=args.destination_ip,
        source_ip=args.source_ip,
        port_base=args.port_base,
        stripe_count=args.stripes,
        chunk_bytes=args.chunk_bytes,
        timeout_s=args.timeout_s,
        socket_buffer_bytes=args.socket_buffer_bytes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "recv-file":
        result = _run_recv_file_args(args)
    elif args.cmd == "send-file":
        result = _run_send_file_args(args)
    else:
        raise AssertionError(args.cmd)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
