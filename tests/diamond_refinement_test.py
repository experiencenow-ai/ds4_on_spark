import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer

from scripts import diamond_refinement_domain as diamond
from scripts._lib.diamond_local_model import DiamondLocalModelClient


SYNTHETIC_DIAMOND_SOURCE = """def answer(value):
    return value + 1
"""


class _DiamondModelHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        _DiamondModelHandler.requests.append(payload)
        body = json.dumps({"candidate_source": SYNTHETIC_DIAMOND_SOURCE}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class DiamondRefinementTest(unittest.TestCase):
    def setUp(self) -> None:
        _DiamondModelHandler.requests = []

    def _client(self) -> tuple[DiamondLocalModelClient, ThreadingHTTPServer]:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _DiamondModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}/diamond"
        return DiamondLocalModelClient(endpoint, provider_id="spark2-test-local"), server

    def test_synthetic_inline_path_produces_verified_diamond_delta(self) -> None:
        client, server = self._client()
        try:
            record = diamond.run_synthetic(client)
            self.assertEqual(
                (
                    record["format"],
                    record["status"],
                    record["frontier_call_count"],
                    record["local_model_call_count"],
                    record["sandbox_isolation"],
                    record["behavior"]["byte_identical_output"],
                ),
                (diamond.FORMAT, "passed", 0, 1, True, True),
            )
            self.assertGreater(record["diamond_delta"], 0)
            self.assertEqual(record["source"]["audit"]["loc"], 4)
            self.assertEqual(record["candidate"]["audit"]["loc"], 2)
            self.assertEqual(record["candidate"]["audit"]["single_caller_helper_count"], 0)
            self.assertIn("-def _plus_one", record["candidate"]["diff"])
            self.assertIn("score_candidate", [node["node"] for node in record["nodes"]])
            self.assertEqual(_DiamondModelHandler.requests[0]["task"], "diamond_refactor")
        finally:
            server.shutdown()
            server.server_close()

    def test_invalid_model_candidate_is_rejected_by_verification(self) -> None:
        class BadModel:
            provider_id = "spark2-test-bad"

            def propose_refactor(self, source: str, candidate_kind: str) -> dict:
                return {
                    "provider_id": self.provider_id,
                    "api_style": "unit",
                    "candidate_kind": candidate_kind,
                    "candidate_source": "def nope(:\n",
                }

        record = diamond.run_synthetic(BadModel())
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["local_model_call_count"], 1)
        self.assertFalse(record["candidate"]["syntax"]["valid"])

if __name__ == "__main__":
    unittest.main()
