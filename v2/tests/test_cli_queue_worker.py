from __future__ import annotations

import contextlib
import io
import unittest

from ds4_infer.cli import _build_parser


class QueueWorkerCliTests(unittest.TestCase):
    def test_queue_work_requires_topology(self) -> None:
        parser = _build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["queue-work", "--queue-dir", "/tmp/q", "--profiles-dir", "/tmp/p"])

    def test_queue_worker_requires_topology(self) -> None:
        parser = _build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["queue-worker", "--queue-dir", "/tmp/q", "--profiles-dir", "/tmp/p"])


if __name__ == "__main__":
    unittest.main()
