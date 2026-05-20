#!/usr/bin/env python3
"""Fast raw-TCP copies across directly connected Spark ring neighbors.

SSH is used only to start a Python helper on each Spark. The payload moves over
the declared 200G ring IPs from sparknetwork.json, without SSH encryption.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import select
import shlex
import subprocess
import sys
import threading
import time
from typing import Any


HELPER = r'''
import argparse
import json
import os
import posixpath
import queue
import socket
import stat
import sys
import threading
import time


def set_sock_buffers(sock, mib):
    size = int(mib) * 1024 * 1024
    for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
        try:
            sock.setsockopt(socket.SOL_SOCKET, opt, size)
        except OSError:
            pass


def clean_rel(path):
    path = path.replace("\\", "/")
    path = posixpath.normpath(path)
    if path in ("", "."):
        return "."
    if path.startswith("/") or path == ".." or path.startswith("../"):
        raise ValueError("unsafe relative path: %r" % path)
    return path


def dst_path(base, rel):
    rel = clean_rel(rel)
    if rel == ".":
        return base
    return os.path.join(base, *rel.split("/"))


def recv_exact(fp, length, out_fd, offset):
    remaining = int(length)
    pos = int(offset)
    buf = bytearray(8 * 1024 * 1024)
    view = memoryview(buf)
    while remaining > 0:
        nwant = min(len(buf), remaining)
        nread = fp.readinto(view[:nwant])
        if not nread:
            raise RuntimeError("short read")
        os.pwrite(out_fd, view[:nread], pos)
        pos += nread
        remaining -= nread


def handle_recv_conn(conn, dst_base, stats, lock, done_q):
    try:
        set_sock_buffers(conn, 64)
        fp = conn.makefile("rb", buffering=0)
        while True:
            line = fp.readline()
            if not line:
                break
            msg = json.loads(line.decode("utf-8"))
            kind = msg.get("kind")
            if kind == "done":
                break
            rel = clean_rel(str(msg.get("rel", ".")))
            path = dst_path(dst_base, rel)
            if kind == "dir":
                os.makedirs(path, exist_ok=True)
                continue
            if kind == "symlink":
                os.makedirs(os.path.dirname(path), exist_ok=True)
                target = str(msg.get("target", ""))
                try:
                    os.symlink(target, path)
                except FileExistsError:
                    pass
                continue
            if kind != "file":
                raise RuntimeError("unknown message kind: %r" % kind)
            size = int(msg["size"])
            length = int(msg["length"])
            offset = int(msg["offset"])
            mode = int(msg.get("mode", 0o644))
            mtime_ns = msg.get("mtime_ns")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if length > 0:
                with lock:
                    if stats["first"] is None:
                        stats["first"] = time.time()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT, mode)
            try:
                try:
                    os.fchmod(fd, mode & 0o777)
                except OSError:
                    pass
                os.ftruncate(fd, size)
                recv_exact(fp, length, fd, offset)
            finally:
                os.close(fd)
            if mtime_ns is not None:
                try:
                    os.utime(path, ns=(int(mtime_ns), int(mtime_ns)), follow_symlinks=False)
                except OSError:
                    pass
            with lock:
                stats["bytes"] += length
                stats["chunks"] += 1
    finally:
        try:
            conn.close()
        finally:
            done_q.put(1)


def recv_main(args):
    os.makedirs(args.dst_base, exist_ok=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    set_sock_buffers(sock, args.socket_buffer_mib)
    sock.bind((args.listen, int(args.port)))
    sock.listen(int(args.streams))
    print("READY %s:%d" % (args.listen, int(args.port)), flush=True)
    stats = {"bytes": 0, "chunks": 0, "first": None}
    lock = threading.Lock()
    done_q = queue.Queue()
    for _ in range(int(args.streams)):
        conn, _addr = sock.accept()
        t = threading.Thread(target=handle_recv_conn, args=(conn, args.dst_base, stats, lock, done_q), daemon=True)
        t.start()
    for _ in range(int(args.streams)):
        done_q.get()
    start = stats["first"] if stats["first"] is not None else time.time()
    elapsed = max(time.time() - start, 0.001)
    gbps = (stats["bytes"] * 8.0) / elapsed / 1e9
    print("RECV_DONE bytes=%d chunks=%d seconds=%.3f gbps=%.3f" % (stats["bytes"], stats["chunks"], elapsed, gbps), flush=True)


def send_header(sock, obj):
    data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
    sock.sendall(data)


def send_file_range(sock, path, rel, offset, length, size, mode, mtime_ns):
    send_header(sock, {
        "kind": "file",
        "rel": rel,
        "offset": int(offset),
        "length": int(length),
        "size": int(size),
        "mode": int(mode & 0o777),
        "mtime_ns": int(mtime_ns),
    })
    fd = os.open(path, os.O_RDONLY)
    try:
        sent_total = 0
        while sent_total < length:
            sent = os.sendfile(sock.fileno(), fd, int(offset) + sent_total, int(length) - sent_total)
            if sent == 0:
                raise RuntimeError("sendfile returned 0")
            sent_total += sent
    finally:
        os.close(fd)


def enqueue_path_tasks(src, root_name, chunk_size, tasks):
    st = os.lstat(src)
    if stat.S_ISREG(st.st_mode):
        rel = clean_rel(root_name)
        size = int(st.st_size)
        off = 0
        while off < size:
            n = min(int(chunk_size), size - off)
            tasks.append(("file", src, rel, off, n, size, st.st_mode, st.st_mtime_ns))
            off += n
        if size == 0:
            tasks.append(("file", src, rel, 0, 0, 0, st.st_mode, st.st_mtime_ns))
        return
    if not stat.S_ISDIR(st.st_mode):
        raise SystemExit("source must be a regular file or directory: %s" % src)
    src_root = src.rstrip("/")
    def rel_for(path):
        tail = os.path.relpath(path, src_root).replace(os.sep, "/")
        if tail == ".":
            return clean_rel(root_name)
        return clean_rel(posixpath.join(root_name, tail))
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dst = os.lstat(dirpath)
        tasks.append(("dir", None, rel_for(dirpath), 0, 0, 0, dst.st_mode, dst.st_mtime_ns))
        for name in list(dirnames):
            path = os.path.join(dirpath, name)
            dst = os.lstat(path)
            if stat.S_ISLNK(dst.st_mode):
                tasks.append(("symlink", os.readlink(path), rel_for(path), 0, 0, 0, dst.st_mode, dst.st_mtime_ns))
                dirnames.remove(name)
        for name in filenames:
            path = os.path.join(dirpath, name)
            fst = os.lstat(path)
            rel = rel_for(path)
            if stat.S_ISLNK(fst.st_mode):
                tasks.append(("symlink", os.readlink(path), rel, 0, 0, 0, fst.st_mode, fst.st_mtime_ns))
                continue
            if not stat.S_ISREG(fst.st_mode):
                continue
            size = int(fst.st_size)
            off = 0
            while off < size:
                n = min(int(chunk_size), size - off)
                tasks.append(("file", path, rel, off, n, size, fst.st_mode, fst.st_mtime_ns))
                off += n
            if size == 0:
                tasks.append(("file", path, rel, 0, 0, 0, fst.st_mode, fst.st_mtime_ns))


def send_worker(idx, dst_ips, port, task_q, stats, lock, socket_buffer_mib):
    ip = dst_ips[idx % len(dst_ips)]
    sock = socket.create_connection((ip, int(port)), timeout=30)
    set_sock_buffers(sock, socket_buffer_mib)
    try:
        while True:
            task = task_q.get()
            if task is None:
                send_header(sock, {"kind": "done"})
                return
            kind, path, rel, off, length, size, mode, mtime_ns = task
            if kind == "dir":
                send_header(sock, {"kind": "dir", "rel": rel, "mode": int(mode & 0o777), "mtime_ns": int(mtime_ns)})
            elif kind == "symlink":
                send_header(sock, {"kind": "symlink", "rel": rel, "target": path})
            else:
                send_file_range(sock, path, rel, off, length, size, mode, mtime_ns)
                with lock:
                    stats["bytes"] += int(length)
                    stats["chunks"] += 1
    finally:
        sock.close()


def send_main(args):
    tasks = []
    enqueue_path_tasks(args.src, args.root_name, int(args.chunk_mib) * 1024 * 1024, tasks)
    total_bytes = sum(int(t[4]) for t in tasks if t[0] == "file")
    dst_ips = [x for x in args.dst_ips.split(",") if x]
    if len(dst_ips) == 0:
        raise SystemExit("--dst-ips is empty")
    task_q = queue.Queue(maxsize=max(2 * int(args.streams), 8))
    stats = {"bytes": 0, "chunks": 0}
    lock = threading.Lock()
    threads = []
    start = time.time()
    for i in range(int(args.streams)):
        t = threading.Thread(target=send_worker, args=(i, dst_ips, args.port, task_q, stats, lock, int(args.socket_buffer_mib)), daemon=True)
        t.start()
        threads.append(t)
    for task in tasks:
        task_q.put(task)
    for _ in threads:
        task_q.put(None)
    for t in threads:
        t.join()
    if stats["bytes"] != total_bytes:
        raise SystemExit("sent %d bytes, expected %d bytes" % (stats["bytes"], total_bytes))
    elapsed = max(time.time() - start, 0.001)
    gbps = (stats["bytes"] * 8.0) / elapsed / 1e9
    print("SEND_DONE bytes=%d expected_bytes=%d chunks=%d seconds=%.3f gbps=%.3f" % (stats["bytes"], total_bytes, stats["chunks"], elapsed, gbps), flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("recv")
    rp.add_argument("--listen", default="0.0.0.0")
    rp.add_argument("--port", required=True, type=int)
    rp.add_argument("--dst-base", required=True)
    rp.add_argument("--streams", required=True, type=int)
    rp.add_argument("--socket-buffer-mib", default=64, type=int)
    sp = sub.add_parser("send")
    sp.add_argument("--dst-ips", required=True)
    sp.add_argument("--port", required=True, type=int)
    sp.add_argument("--src", required=True)
    sp.add_argument("--root-name", required=True)
    sp.add_argument("--streams", required=True, type=int)
    sp.add_argument("--chunk-mib", default=256, type=int)
    sp.add_argument("--socket-buffer-mib", default=64, type=int)
    args = ap.parse_args()
    if args.cmd == "recv":
        recv_main(args)
    else:
        send_main(args)


if __name__ == "__main__":
    main()
'''


def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, **kwargs)


def parse_spec(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise SystemExit("expected node:/path, got: %s" % spec)
    node, path = spec.split(":", 1)
    if not node or not path.startswith("/"):
        raise SystemExit("expected node:/absolute/path, got: %s" % spec)
    return node, path


def load_topology(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ip_no_cidr(value: str) -> str:
    return value.split("/", 1)[0]


def ring_dest_ips(topology: dict[str, Any], src: str, dst: str, link: str) -> list[str]:
    ips: list[str] = []
    for entry in topology["ring_200g"]["links"]:
        a = entry["a"]
        b = entry["b"]
        if a["node"] == src and b["node"] == dst:
            ips.append(ip_no_cidr(b["ipv4"]))
        elif b["node"] == src and a["node"] == dst:
            ips.append(ip_no_cidr(a["ipv4"]))
    if not ips:
        order = topology["ring_200g"].get("order", [])
        raise SystemExit("%s and %s are not direct 200G neighbors in sparknetwork.json. Copy hop-by-hop along: %s" % (src, dst, " -> ".join(order)))
    if link in ("first", "a", "A"):
        return ips[:1]
    if link in ("second", "b", "B"):
        if len(ips) < 2:
            raise SystemExit("requested second link, but only one link is declared")
        return ips[1:2]
    if link != "both":
        raise SystemExit("--link must be both, first, or second")
    return ips


def remote_json(node: str, code: str, *args: str) -> Any:
    remote = "python3 -c %s %s" % (shlex.quote(code), " ".join(shlex.quote(a) for a in args))
    cp = run(["ssh", node, remote], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode != 0:
        raise SystemExit(cp.stderr.strip() or "remote command failed on %s" % node)
    return json.loads(cp.stdout)


def remote_stat(node: str, path: str) -> dict[str, Any]:
    code = r'''
import json, os, stat, sys
p = sys.argv[1]
st = os.lstat(p)
kind = "dir" if stat.S_ISDIR(st.st_mode) else "file" if stat.S_ISREG(st.st_mode) else "other"
print(json.dumps({"kind": kind, "size": st.st_size, "mode": st.st_mode & 0o777, "basename": os.path.basename(p.rstrip("/"))}))
'''
    return remote_json(node, code, path)


def dry_run_stat(src_path: str, engine: str, error: BaseException) -> dict[str, Any]:
    kind = "dir" if src_path.endswith("/") else "file"
    if engine == "native":
        kind = "file"
    basename = posixpath.basename(src_path.rstrip("/")) or "."
    mode = 0o755 if kind == "dir" else 0o644
    error_text = str(error).strip()
    if "\n" in error_text:
        error_text = error_text.splitlines()[-1]
    return {
        "kind": kind,
        "size": 0,
        "mode": mode,
        "basename": basename,
        "dry_run_stat_error": error_text,
    }


def remote_is_dir(node: str, path: str) -> bool:
    code = 'import json, os, sys; print(json.dumps(os.path.isdir(sys.argv[1])))'
    try:
        return bool(remote_json(node, code, path))
    except SystemExit:
        return path.endswith("/")


def dst_layout(dst_node: str, dst_path: str, src_base: str, src_kind: str) -> tuple[str, str]:
    src_name = posixpath.basename(src_base.rstrip("/"))
    if src_kind == "file":
        if dst_path.endswith("/") or remote_is_dir(dst_node, dst_path):
            return dst_path.rstrip("/"), src_name
        return posixpath.dirname(dst_path) or "/", posixpath.basename(dst_path)
    if dst_path.endswith("/") or remote_is_dir(dst_node, dst_path):
        return dst_path.rstrip("/"), src_name
    return posixpath.dirname(dst_path) or "/", posixpath.basename(dst_path)


def start_helper(node: str, remote_cmd: str) -> subprocess.Popen[str]:
    proc = subprocess.Popen(["ssh", node, remote_cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert proc.stdin is not None
    proc.stdin.write(HELPER)
    proc.stdin.close()
    return proc


def start_shell(node: str, script: str) -> subprocess.Popen[str]:
    remote_cmd = "sh -lc %s" % shlex.quote(script)
    return subprocess.Popen(["ssh", node, remote_cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)


def wait_ready(proc: subprocess.Popen[str], timeout: float) -> list[str]:
    assert proc.stdout is not None
    lines: list[str] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _unused_w, _unused_x = select.select([proc.stdout], [], [], 0.05)
        if ready:
            line = proc.stdout.readline()
            if line:
                sys.stdout.write("[recv] " + line)
                sys.stdout.flush()
                lines.append(line)
                if line.startswith("READY "):
                    return lines
            elif proc.poll() is not None:
                raise SystemExit("receiver exited early")
        elif proc.poll() is not None:
            raise SystemExit("receiver exited early")
    raise SystemExit("receiver did not become ready")


def drain(prefix: str, proc: subprocess.Popen[str], lines: list[str]) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(prefix + line)
        sys.stdout.flush()
        lines.append(line)


def shq(value: str) -> str:
    return shlex.quote(value)


def native_batch_scripts(src_path: str, dst_path: str, dst_ips: list[str], port: int, chunk_bytes: int, chunks: range) -> tuple[str, str]:
    recv_lines: list[str] = []
    send_lines: list[str] = []
    recv_lines.append("set -u")
    recv_lines.append("mkdir -p %s" % shq(posixpath.dirname(dst_path) or "/"))
    recv_lines.append("pids=\"\"")
    recv_lines.append("fail=0")
    for slot, chunk in enumerate(chunks):
        recv_lines.append("(nc -l %d | dd of=%s bs=%d seek=%d conv=notrunc status=none) &" % (port + slot, shq(dst_path), chunk_bytes, chunk))
        recv_lines.append("pids=\"$pids $!\"")
    recv_lines.append("echo READY native")
    recv_lines.append("for p in $pids; do wait \"$p\" || fail=1; done")
    recv_lines.append("exit \"$fail\"")
    send_lines.append("set -u")
    send_lines.append("pids=\"\"")
    send_lines.append("fail=0")
    for slot, chunk in enumerate(chunks):
        ip = dst_ips[slot % len(dst_ips)]
        send_lines.append("(dd if=%s bs=%d skip=%d count=1 status=none | nc -N %s %d) &" % (shq(src_path), chunk_bytes, chunk, shq(ip), port + slot))
        send_lines.append("pids=\"$pids $!\"")
    send_lines.append("for p in $pids; do wait \"$p\" || fail=1; done")
    send_lines.append("exit \"$fail\"")
    return "\n".join(recv_lines), "\n".join(send_lines)


def native_copy_file(src_node: str, src_path: str, dst_node: str, dst_file: str, dst_ips: list[str], args: argparse.Namespace, size: int, mode: int) -> None:
    chunk_bytes = int(args.chunk_mib) * 1024 * 1024
    copied = 0
    start = None
    if chunk_bytes <= 0:
        raise SystemExit("--chunk-mib must be positive")
    if args.parallel <= 0:
        raise SystemExit("--parallel must be positive")
    chunks_total = (int(size) + chunk_bytes - 1) // chunk_bytes
    setup = "mkdir -p %s && truncate -s %d %s && chmod %o %s" % (shq(posixpath.dirname(dst_file) or "/"), size, shq(dst_file), int(mode) & 0o777, shq(dst_file))
    cp = run(["ssh", dst_node, setup], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode != 0:
        raise SystemExit(cp.stderr.strip() or "native destination setup failed on %s" % dst_node)
    for first in range(0, chunks_total, int(args.parallel)):
        last = min(first + int(args.parallel), chunks_total)
        recv_script, send_script = native_batch_scripts(src_path, dst_file, dst_ips, int(args.port), chunk_bytes, range(first, last))
        recv = start_shell(dst_node, recv_script)
        recv_lines = wait_ready(recv, 30)
        recv_thread = threading.Thread(target=drain, args=("[recv] ", recv, recv_lines), daemon=True)
        recv_thread.start()
        if start is None:
            start = time.time()
        sender = start_shell(src_node, send_script)
        send_lines: list[str] = []
        drain("[send] ", sender, send_lines)
        send_rc = sender.wait()
        recv_rc = recv.wait(timeout=120)
        if send_rc != 0 or recv_rc != 0:
            raise SystemExit("native copy failed: sender rc=%d receiver rc=%d" % (send_rc, recv_rc))
        copied = min(int(size), last * chunk_bytes)
        print("native progress bytes=%d/%d" % (copied, int(size)), flush=True)
    elapsed = max(time.time() - (start if start is not None else time.time()), 0.001)
    gbps = (int(size) * 8.0) / elapsed / 1e9
    print("NATIVE_DONE bytes=%d chunks=%d seconds=%.3f gbps=%.3f" % (int(size), chunks_total, elapsed, gbps), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Copy files over raw TCP on direct Spark 200G ring links.")
    ap.add_argument("src", help="source spec, e.g. spark2:/models/foo.gguf")
    ap.add_argument("dst", help="destination spec, e.g. spark3:/models/")
    ap.add_argument("--topology", default="sparknetwork.json")
    ap.add_argument("--port", default=24040, type=int)
    ap.add_argument("--parallel", default=8, type=int, help="parallel TCP streams")
    ap.add_argument("--chunk-mib", default=256, type=int)
    ap.add_argument("--socket-buffer-mib", default=64, type=int)
    ap.add_argument("--link", default="both", choices=["both", "first", "second"])
    ap.add_argument("--engine", default="auto", choices=["auto", "native", "python"], help="native uses nc/dd for regular files; python handles files and directories")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    src_node, src_path = parse_spec(args.src)
    dst_node, dst_path = parse_spec(args.dst)
    topology = load_topology(args.topology)
    dst_ips = ring_dest_ips(topology, src_node, dst_node, args.link)
    try:
        st = remote_stat(src_node, src_path)
    except SystemExit as exc:
        if not args.dry_run:
            raise
        st = dry_run_stat(src_path, args.engine, exc)
    if st["kind"] not in ("file", "dir"):
        raise SystemExit("source is not a regular file or directory: %s" % args.src)
    dst_base, root_name = dst_layout(dst_node, dst_path, st["basename"], st["kind"])
    engine = "native" if args.engine in ("auto", "native") and st["kind"] == "file" else "python"
    if args.engine == "native" and st["kind"] != "file":
        raise SystemExit("--engine native only supports regular files")
    print("plan: %s:%s -> %s:%s" % (src_node, src_path, dst_node, dst_path))
    print("ring destination IPs: %s" % ",".join(dst_ips))
    print("engine=%s streams=%d chunk_mib=%d dst_base=%s root_name=%s" % (engine, args.parallel, args.chunk_mib, dst_base, root_name))
    if args.dry_run and "dry_run_stat_error" in st:
        print("dry-run source stat skipped: %s" % st["dry_run_stat_error"])
    if args.dry_run:
        return
    if engine == "native":
        native_copy_file(src_node, src_path, dst_node, posixpath.join(dst_base, root_name), dst_ips, args, int(st["size"]), int(st["mode"]))
        return
    recv_cmd = "python3 -u - recv --listen 0.0.0.0 --port %d --dst-base %s --streams %d --socket-buffer-mib %d" % (args.port, shlex.quote(dst_base), args.parallel, args.socket_buffer_mib)
    send_cmd = "python3 -u - send --dst-ips %s --port %d --src %s --root-name %s --streams %d --chunk-mib %d --socket-buffer-mib %d" % (
        shlex.quote(",".join(dst_ips)),
        args.port,
        shlex.quote(src_path),
        shlex.quote(root_name),
        args.parallel,
        args.chunk_mib,
        args.socket_buffer_mib,
    )
    recv = start_helper(dst_node, recv_cmd)
    recv_lines = wait_ready(recv, 30)
    recv_thread = threading.Thread(target=drain, args=("[recv] ", recv, recv_lines), daemon=True)
    recv_thread.start()
    sender = start_helper(src_node, send_cmd)
    send_lines: list[str] = []
    drain("[send] ", sender, send_lines)
    send_rc = sender.wait()
    recv_rc = recv.wait(timeout=120)
    if send_rc != 0 or recv_rc != 0:
        raise SystemExit("copy failed: sender rc=%d receiver rc=%d" % (send_rc, recv_rc))


if __name__ == "__main__":
    main()
