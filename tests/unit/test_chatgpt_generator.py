import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from app.services.rag.generator.chatgpt_generator import ChatGPTGenerator


class TestChatGPTGenerator(unittest.TestCase):

    @patch("app.services.rag.generator.chatgpt_generator.OpenAI")
    @patch("app.services.rag.generator.chatgpt_generator.settings")
    @patch("app.services.rag.generator.chatgpt_generator.rag_config", {
        "generator": {
            "model_name": "gpt-test",
            "temperature": 0.1,
            "max_retries": 2,
            "streaming": False,
            "system_prompt": "You are helpful.",
            "context": {
                "max_items": 3,
                "max_chars_per_item": 1000,
            },
        }
    })
    def test_init_success(self, mock_settings, mock_openai):
        mock_settings.OPENAI_API_KEY = "fake-key"

        gen = ChatGPTGenerator()

        self.assertEqual(gen.model_name, "gpt-test")
        self.assertEqual(gen.temperature, 0.1)
        self.assertEqual(gen.system_prompt, "You are helpful.")
        mock_openai.assert_called_once_with(api_key="fake-key")

    @patch("app.services.rag.generator.chatgpt_generator.settings")
    @patch("app.services.rag.generator.chatgpt_generator.rag_config", {
        "generator": {
            "model_name": "gpt-test",
            "system_prompt": "You are helpful.",
        }
    })
    def test_init_raises_without_api_key(self, mock_settings):
        mock_settings.OPENAI_API_KEY = None

        with self.assertRaises(ValueError):
            ChatGPTGenerator()

    @patch("app.services.rag.generator.chatgpt_generator.OpenAI")
    @patch("app.services.rag.generator.chatgpt_generator.settings")
    @patch("app.services.rag.generator.chatgpt_generator.rag_config", {
        "generator": {
            "model_name": "gpt-test",
            "temperature": 0.1,
            "system_prompt": "System prompt",
            "context": {},
        }
    })
    def test_build_messages_with_history(self, mock_settings, mock_openai):
        mock_settings.OPENAI_API_KEY = "fake-key"
        gen = ChatGPTGenerator()

        history = [{"role": "assistant", "content": "你好"}]
        messages = gen._build_messages(
            query="Myki怎么办？",
            context="PTV资料",
            chat_history=history,
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1], history[0])
        self.assertEqual(messages[2]["role"], "user")
        self.assertIn("Myki怎么办？", messages[2]["content"])
        self.assertIn("PTV资料", messages[2]["content"])

    @patch("app.services.rag.generator.chatgpt_generator.OpenAI")
    @patch("app.services.rag.generator.chatgpt_generator.settings")
    @patch("app.services.rag.generator.chatgpt_generator.rag_config", {
        "generator": {
            "model_name": "gpt-test",
            "temperature": 0.1,
            "system_prompt": "System prompt",
            "context": {},
        }
    })
    def test_generate_text_calls_openai(self, mock_settings, mock_openai):
        mock_settings.OPENAI_API_KEY = "fake-key"

        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="生成结果")
                )
            ]
        )
        mock_client.chat.completions.create.return_value = mock_response

        gen = ChatGPTGenerator()

        with patch.object(gen, "_build_context", return_value="mock context"):
            result = gen.generate_text("问题", [])

        self.assertEqual(result, "生成结果")

        mock_client.chat.completions.create.assert_called_once()
        kwargs = mock_client.chat.completions.create.call_args.kwargs

        self.assertEqual(kwargs["model"], "gpt-test")
        self.assertEqual(kwargs["temperature"], 0.1)
        self.assertIn("messages", kwargs)

    @patch("app.services.rag.generator.chatgpt_generator.OpenAI")
    @patch("app.services.rag.generator.chatgpt_generator.settings")
    @patch("app.services.rag.generator.chatgpt_generator.rag_config", {
        "generator": {
            "model_name": "gpt-test",
            "temperature": 0.1,
            "system_prompt": "System prompt",
            "context": {},
        }
    })
    def test_stream_text_yields_chunks(self, mock_settings, mock_openai):
        mock_settings.OPENAI_API_KEY = "fake-key"

        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_client.chat.completions.create.return_value = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="你")
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="好")
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None)
                    )
                ]
            ),
        ]

        gen = ChatGPTGenerator()

        with patch.object(gen, "_build_context", return_value="mock context"):
            chunks = list(gen.stream_text("问题", []))

        self.assertEqual(chunks, ["你", "好"])

        kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertTrue(kwargs["stream"])


if __name__ == "__main__":
    unittest.main()