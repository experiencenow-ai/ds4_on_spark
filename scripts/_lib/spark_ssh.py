"""Shared Spark SSH command construction."""

from __future__ import annotations

from collections.abc import Sequence


def ssh_prefix(ssh_target: str, jump_target: str | None, common_opts: Sequence[str]) -> list[str]:
	cmd = ["ssh", *common_opts]
	if jump_target is not None:
		cmd.extend(["-J", jump_target])
	cmd.append(ssh_target)
	return cmd
