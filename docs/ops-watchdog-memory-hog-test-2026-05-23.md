# Spark Watchdog Memory-Hog Wedge Test - 2026-05-23

Purpose: verify the watchdog no longer depends on a finite vLLM process-name
allowlist once local SSH is broken. After an SSH-banner failure, the node should
kill broad memory hogs while preserving only the OS, network, and SSH basics.

Target: Spark7, `thinkstation-pgx`, non-gateway node.

Deployed watchdog source:

- Repo source: `scripts/ds4_sshd_watchdog.sh`
- Live path: `/usr/local/sbin/ds4-sshd-watchdog`
- Live hash on Spark0-Spark7:
  `bb6e176cbb8506fa84d5ec542ba6f682fabe8737bac5af1dc17eee3c809e2240`

Command:

```bash
DS4_SUDO_PASSWORD=... \
DS4_WATCHDOG_TEST_TAG='DS4MEMHOG::watchdog-port-wedge' \
DS4_WATCHDOG_TEST_MEM_MIB=768 \
DS4_WATCHDOG_TEST_TIMEOUT=210 \
DS4_WATCHDOG_TEST_POLL=5 \
scripts/ds4_watchdog_wedge_test.sh spark7
```

The test starts a non-vLLM-tagged Python workload that allocates memory, stops
`ssh.socket` and `ssh.service`, binds port `22`, and intentionally does not
send an SSH banner. Because the tag does not match `VLLM::` or `vllm serve`,
the recovery depends on the generic top-memory-process killer.

Observed output:

```text
== precheck: spark7 SSH banner ==
SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.16
== starting synthetic SSH-port wedge on spark7: tag=DS4MEMHOG::watchdog-port-wedge mem_mib=768 ==
== waiting for watchdog recovery, timeout 210s ==
still wedged at 0s: ssh: connect to host 192.168.1.236 port 22: Connection refused
still wedged at 5s: Connection timed out during banner exchange
still wedged at 15s: Connection timed out during banner exchange
still wedged at 25s: Connection timed out during banner exchange
still wedged at 36s: kex_exchange_identification: read: Connection reset by peer
SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.16
```

Watchdog journal evidence:

```text
May 23 11:02:12 thinkstation-pgx ds4-sshd-watchdog[98139]: local SSH banner probe failed; restarting ssh
May 23 11:02:16 thinkstation-pgx ds4-sshd-watchdog[98145]: SSH banner still failing after restart; escalating to runtime and memory-hog kill
May 23 11:02:16 thinkstation-pgx ds4-sshd-watchdog[98146]: killing allowlisted and memory-heavy runtimes
May 23 11:02:16 thinkstation-pgx ds4-sshd-watchdog[98184]: killing top memory process pid=98120 rss_kb=798364 comm=python3 args=python3 /tmp/ds4_watchdog_vllm_port_wedge.py DS4MEMHOG::watchdog-port-wedge 768
May 23 11:02:16 thinkstation-pgx ds4-sshd-watchdog[98192]: killing top memory process pid=98134 rss_kb=796188 comm=python3 args=python3 /tmp/ds4_watchdog_vllm_port_wedge.py DS4MEMHOG::watchdog-port-wedge 768
May 23 11:02:23 thinkstation-pgx ds4-sshd-watchdog[98569]: SSH banner recovered after runtime and memory-hog kill
```

Result: PASS.

- SSH went unhealthy.
- Restart alone did not recover it.
- The process did not match the vLLM allowlist.
- The watchdog killed the largest memory-heavy processes.
- SSH recovered without physical access or remote power cycling.
- Postcheck showed `ssh`, `ds4-sshd-watchdog.timer`, and
  `ds4-rescue-agent.service` active.

Limits: this still cannot recover a true kernel panic, firmware/PCIe lockup,
or hard power fault. Those remain remote-power/PDU territory.
