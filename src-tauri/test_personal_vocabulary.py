import unittest

import httpx

from whisper_engine import cloud_quality as quality


class TestPersonalVocabulary(unittest.TestCase):
    def test_final_spellings_resolve_variants_without_aliases(self):
        examples = [
            ("Apri traffic vice.", "Traflix Voice", "Apri Traflix Voice."),
            ("Uso grock per dettare.", "Groq", "Uso Groq per dettare."),
            ("Vorrei provare whisper flow.", "Wispr Flow", "Vorrei provare Wispr Flow."),
            ("Avvia traflixvoice.", "Traflix Voice", "Avvia Traflix Voice."),
            ("Uso grock e poi torno su grock.", "Groq", "Uso Groq e poi torno su Groq."),
            ("Sto scrivendo TypeScrypt.", "TypeScript", "Sto scrivendo TypeScript."),
        ]
        for text, vocabulary, expected in examples:
            with self.subTest(text=text):
                self.assertEqual(quality.apply_personal_vocabulary(text, vocabulary), expected)

    def test_vocabulary_does_not_add_terms_or_change_unrelated_words(self):
        examples = [
            ("Non inviare i 250 euro a Marco.", "Traflix Voice\nGroq\nWispr Flow"),
            ("This group is ready.", "Groq"),
            ("Questa casa è molto bella.", "Cosa"),
            ("Non cambiare uno in due.", "Uno\nDue"),
            ("La misura è 50 kg e il saldo è -250 euro.", "Groq\nTraflix Voice"),
            ("Il percorso è C:\\projects\\trafficvice.", "Traflix Voice"),
            ("Visita https://trafficvice.example oppure usa `traffic vice`.", "Traflix Voice"),
        ]
        for text, vocabulary in examples:
            with self.subTest(text=text):
                self.assertEqual(quality.apply_personal_vocabulary(text, vocabulary), text)

    def test_ambiguous_final_spellings_are_left_unchanged(self):
        text = "Uso abcdefghi per dettare."
        self.assertEqual(quality.apply_personal_vocabulary(text, "Abcdefghij\nAbcdefghik"), text)

    def test_short_vocabulary_dictation_needs_no_llm(self):
        with httpx.Client(transport=httpx.MockTransport(lambda _: self.fail("Unexpected LLM request"))) as client:
            result = quality.correct_cloud_transcript(
                client, quality.CloudTranscript("traffic vice"), "it", lambda: False, "Traflix Voice")
        self.assertEqual(result.text, "Traflix Voice")

    def test_vocabulary_survives_llm_timeout(self):
        def timeout(request):
            raise httpx.ReadTimeout("synthetic timeout", request=request)

        with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
            result = quality.correct_cloud_transcript(
                client, quality.CloudTranscript("Uso traffic vice per dettare oggi.", True),
                "it", lambda: False, "Traflix Voice")
        self.assertEqual(result.text, "Uso Traflix Voice per dettare oggi.")


if __name__ == "__main__":
    unittest.main()
