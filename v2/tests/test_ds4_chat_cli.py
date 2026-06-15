from __future__ import annotations

import unittest

from ds4_chat.cli import _chat_text_from_response, _dsapi_chat_payload, _iter_sse_json, _public_messages, _remote_model


class Ds4ChatCliTests(unittest.TestCase):
    def test_remote_model_aliases_current_resident_services(self) -> None:
        self.assertEqual(_remote_model(None, "ds4v"), "kimi27_pp13")
        self.assertEqual(_remote_model(None, "qwen"), "qwen27_bf16_pp13")
        self.assertEqual(_remote_model("gemma", "qwen"), "gemma4_26b_a4b_pp13")
        self.assertEqual(_remote_model("raw-service", "qwen"), "raw-service")

    def test_dsapi_payload_keeps_openai_fields_and_ds4_controls(self) -> None:
        payload = _dsapi_chat_payload(
            model="kimi27_pp13",
            messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "hello", "_ds4": {"usage": {}}}],
            max_tokens=128,
            temperature=0.2,
            timeout_s=90,
            priority=3,
            stream=True,
            ds4_job_class="interactive",
            thinking_budget_tokens=64,
            extra_body={"chat_template_kwargs": {"enable_thinking": True}},
            metadata={"caller": "chat"},
        )
        self.assertEqual(payload["model"], "kimi27_pp13")
        self.assertEqual(payload["messages"], [{"role": "system", "content": "s"}, {"role": "user", "content": "hello"}])
        self.assertEqual(payload["max_tokens"], 128)
        self.assertEqual(payload["priority"], 3)
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["thinking_budget_tokens"], 64)
        self.assertEqual(payload["extra_body"]["chat_template_kwargs"]["enable_thinking"], True)
        self.assertEqual(payload["metadata"], {"caller": "chat"})

    def test_public_messages_filters_private_metadata(self) -> None:
        self.assertEqual(
            _public_messages([{"role": "assistant", "content": "ok", "_ds4": {"elapsed_s": 1.0}}, {"role": "tool"}]),
            [{"role": "assistant", "content": "ok"}],
        )

    def test_iter_sse_json_parses_data_events_until_done(self) -> None:
        events = list(
            _iter_sse_json(
                [
                    b"data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n",
                    b"\n",
                    b"data: [DONE]\n",
                    b"\n",
                ]
            )
        )
        self.assertEqual(events, [{"choices": [{"delta": {"content": "hi"}}]}])

    def test_chat_text_from_response_reads_first_choice(self) -> None:
        self.assertEqual(
            _chat_text_from_response({"choices": [{"message": {"role": "assistant", "content": "answer"}}]}),
            "answer",
        )


if __name__ == "__main__":
    unittest.main()
