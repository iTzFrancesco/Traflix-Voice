import unittest
from unittest.mock import MagicMock, patch

from whisper_engine import transcriber


class TestGroqClientCache(unittest.TestCase):
    def setUp(self):
        transcriber.close_groq_client()

    def tearDown(self):
        transcriber.close_groq_client()

    def test_reuses_client_for_same_key(self):
        client = MagicMock()
        with patch.object(transcriber, "create_groq_client", return_value=client) as create:
            first = transcriber.get_groq_client("key-a")
            second = transcriber.get_groq_client("key-a")

        self.assertIs(first, second)
        create.assert_called_once_with("key-a")
        client.close.assert_not_called()

    def test_replaces_and_closes_client_when_key_changes(self):
        first = MagicMock()
        second = MagicMock()
        with patch.object(
            transcriber, "create_groq_client", side_effect=[first, second]
        ) as create:
            transcriber.get_groq_client("key-a")
            current = transcriber.get_groq_client("key-b")

        self.assertIs(current, second)
        self.assertEqual(create.call_count, 2)
        first.close.assert_called_once_with()

    def test_client_stores_authorization_header(self):
        client = MagicMock()
        with patch.object(transcriber.httpx, "Client", return_value=client) as create:
            transcriber.create_groq_client("key-a")

        self.assertEqual(
            create.call_args.kwargs["headers"],
            {"Authorization": "Bearer key-a"},
        )


if __name__ == "__main__":
    unittest.main()
