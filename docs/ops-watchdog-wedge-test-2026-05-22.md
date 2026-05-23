# Spark Watchdog Wedge Test - 2026-05-22

Purpose: verify the software rescue path can recover a Spark from the practical
failure mode where a vLLM-class workload leaves the node reachable at the power
level but not usable over SSH.

Target: Spark7, `thinkstation-pgx`, non-gateway node.

Command:

```bash
DS4_SUDO_PASSWORD=... DS4_WATCHDOG_TEST_TIMEOUT=210 DS4_WATCHDOG_TEST_POLL=5 scripts/ds4_watchdog_wedge_test.sh spark7
```

The test starts a synthetic allowlisted process with `VLLM::watchdog-port-wedge`
in its command line. It stops `ssh.socket` and `ssh.service`, binds port `22`,
and intentionally does not send an SSH banner. This forces the same watchdog
branch used for overloaded vLLM-style failures without risking Spark3, the
current 10G NAT gateway.

Observed output:

```text
== precheck: spark7 SSH banner ==
SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.16
== starting synthetic VLLM:: SSH-port wedge on spark7 ==
== waiting for watchdog recovery, timeout 210s ==
still wedged at 0s: Connection timed out during banner exchange
still wedged at 10s: ssh: connect to host 192.168.1.236 port 22: Connection refused
SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.16
== postcheck: wedge process and watchdog logs ==
May 22 20:23:58 thinkstation-pgx ds4-sshd-watchdog[81479]: local SSH banner probe failed; restarting ssh
May 22 20:24:02 thinkstation-pgx ds4-sshd-watchdog[81485]: SSH banner still failing after restart; killing allowlisted heavy runtimes
May 22 20:24:02 thinkstation-pgx ds4-sshd-watchdog[81515]: killing processes matching VLLM::
May 22 20:24:09 thinkstation-pgx ds4-sshd-watchdog[81679]: SSH banner recovered after killing allowlisted runtimes
active
active
active
```

Result: PASS.

- SSH went unhealthy.
- Watchdog timer detected the failed local banner.
- Restart alone did not recover the node.
- The watchdog killed the allowlisted `VLLM::` process.
- SSH recovered without physical access or remote power cycling.
- Postcheck showed `ssh`, `ds4-sshd-watchdog.timer`, and
  `ds4-rescue-agent.service` active.

Follow-up: the watchdog was broadened on `2026-05-23` to kill generic top
memory hogs after allowlisted runtime kills. See
[`ops-watchdog-memory-hog-test-2026-05-23.md`](ops-watchdog-memory-hog-test-2026-05-23.md).

Limits: this was a synthetic vLLM-class wedge, not a real `vllm serve` process,
because Spark7 does not currently expose a `vllm` CLI in the default
environment. It exercises the exact watchdog branch that real `vllm serve` and
`VLLM::` processes rely on.
