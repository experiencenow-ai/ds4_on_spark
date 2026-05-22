import unittest

from scripts import launch_vllm_pp3_spark as launcher


class LaunchVllmPP3SparkTest(unittest.TestCase):
	def test_parse_nodes_requires_three_ranks(self) -> None:
		nodes = launcher.parse_nodes("spark3:0:10.10.100.13,spark4:1:10.10.100.14,spark5:2:10.10.100.15")
		self.assertEqual([n.rank for n in nodes], [0, 1, 2])
		self.assertEqual([n.addr for n in nodes], ["10.10.100.13", "10.10.100.14", "10.10.100.15"])
		self.assertEqual(nodes[0].model_path, "/home/spark3/models/hf/deepseek-ai/DeepSeek-V4-Flash")

	def test_parse_node_accepts_rank_specific_interfaces(self) -> None:
		node = launcher.parse_node("spark3:0:10.10.100.13::enp1s0f1np1:enp1s0f1np1")
		self.assertEqual(node.model_path, "/home/spark3/models/hf/deepseek-ai/DeepSeek-V4-Flash")
		self.assertEqual(node.socket_ifname, "enp1s0f1np1")
		self.assertEqual(node.gloo_socket_ifname, "enp1s0f1np1")

	def test_parse_nodes_allows_semicolon_when_ifnames_use_commas(self) -> None:
		nodes = launcher.parse_nodes(
			"spark3:0:10.10.100.13::enp1s0f1np1:enp1s0f1np1;"
			"spark4:1:10.10.100.14::enp1s0f0np0,enp1s0f1np1:enp1s0f0np0;"
			"spark5:2:10.10.100.15::enp1s0f0np0:enp1s0f0np0"
		)
		self.assertEqual([n.host for n in nodes], ["spark3", "spark4", "spark5"])
		self.assertEqual(nodes[1].socket_ifname, "enp1s0f0np0,enp1s0f1np1")

	def test_parse_nodes_rejects_missing_rank(self) -> None:
		with self.assertRaises(ValueError):
			launcher.parse_nodes("spark3:0:192.168.1.110,spark4:2:192.168.1.137,spark5:2:192.168.1.245")

	def test_vllm_args_mark_workers_headless(self) -> None:
		args = launcher.parse_args([
			"status",
			"--nodes", "spark3:0:10.10.100.13,spark4:1:10.10.100.14,spark5:2:10.10.100.15",
		])
		head, worker, _ = launcher.parse_nodes(args.nodes)
		self.assertNotIn("--headless", launcher.vllm_args(head, args))
		self.assertIn("--headless", launcher.vllm_args(worker, args))
		self.assertIn("--pipeline-parallel-size", launcher.vllm_args(head, args))

	def test_env_disables_ib_by_default(self) -> None:
		args = launcher.parse_args(["status"])
		node = launcher.parse_node("spark3:0:10.10.100.13")
		env = " ".join(launcher.env_args(node, args))
		self.assertIn("NCCL_IB_DISABLE=1", env)
		self.assertIn("NCCL_SOCKET_FAMILY=AF_INET", env)
		self.assertIn("NCCL_SOCKET_IFNAME=wlP9s9", env)
		self.assertIn("VLLM_HOST_IP=10.10.100.13", env)
		self.assertIn("GLOO_SOCKET_IFNAME=wlP9s9", env)

	def test_env_uses_rank_specific_interfaces(self) -> None:
		args = launcher.parse_args(["status", "--socket-ifname", "wlP9s9", "--gloo-socket-ifname", "wlP9s9"])
		node = launcher.parse_node("spark4:1:10.10.100.14::enp1s0f0np0,enp1s0f1np1:enp1s0f0np0")
		env = " ".join(launcher.env_args(node, args))
		self.assertIn("NCCL_SOCKET_IFNAME=enp1s0f0np0,enp1s0f1np1", env)
		self.assertIn("GLOO_SOCKET_IFNAME=enp1s0f0np0", env)
		self.assertNotIn("NCCL_SOCKET_IFNAME=wlP9s9", env)

	def test_rank_specific_gloo_can_be_disabled(self) -> None:
		args = launcher.parse_args(["status", "--gloo-socket-ifname", "wlP9s9"])
		node = launcher.parse_node("spark4:1:10.10.100.14::enp1s0f0np0:")
		env = " ".join(launcher.env_args(node, args))
		self.assertIn("NCCL_SOCKET_IFNAME=enp1s0f0np0", env)
		self.assertNotIn("GLOO_SOCKET_IFNAME=", env)

	def test_gloo_socket_ifname_can_be_disabled(self) -> None:
		args = launcher.parse_args(["status", "--gloo-socket-ifname", ""])
		node = launcher.parse_node("spark3:0:10.10.100.13")
		env = " ".join(launcher.env_args(node, args))
		self.assertNotIn("GLOO_SOCKET_IFNAME=", env)

	def test_docker_run_mounts_host_log_dir(self) -> None:
		args = launcher.parse_args(["status", "--host-log-dir", "/tmp/ds4-logs"])
		node = launcher.parse_node("spark3:0:10.10.100.13")
		command = launcher.docker_run_command(node, args)
		self.assertIn("-v /tmp/ds4-logs:/host_tmp", command)


if __name__ == "__main__":
	unittest.main()
