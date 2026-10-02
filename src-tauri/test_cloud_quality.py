import json
import unittest
from unittest.mock import patch

import httpx
import numpy as np

from whisper_engine import cloud_quality as quality, transcriber


class TestCloudQuality(unittest.TestCase):
    def test_reliable_fast_speech_never_calls_corrector(self):
        body = {"text": "Le impostazioni sono state salvate nella cartella corretta.",
                "segments": [{"text": "Le impostazioni sono state salvate nella cartella corretta.",
                              "start": 0, "end": 1, "avg_logprob": -0.05, "no_speech_prob": 0}]}
        transcript = quality.parse_cloud_transcript(json.dumps(body).encode(), True)
        client = httpx.Client(transport=httpx.MockTransport(lambda _: self.fail("Unnecessary request")))
        with client:
            self.assertEqual(quality.correct_cloud_transcript(client, transcript, "it", lambda: False).text,
                             body["text"])

    def test_uncertainty_gate_uses_voice_confidence_not_speed_alone(self):
        for confidence, duration, expected in [(-0.7, 8, True), (-0.46, 1, True),
                                                (-0.46, 8, False), (-0.05, 1, False)]:
            with self.subTest(confidence=confidence, duration=duration):
                body = {"text": "Questa frase ha alcune parole da verificare.", "segments": [
                    {"text": "Questa frase ha alcune parole da verificare.", "avg_logprob": confidence,
                     "no_speech_prob": 0, "start": 0, "end": duration}]}
                result = quality.parse_cloud_transcript(json.dumps(body).encode(), True)
                self.assertEqual(result.uncertain, expected)

    def test_grammatical_clauses_do_not_trigger_unnecessary_corrections(self):
        for text in ("Per noi è importante mantenere i nomi originali.",
                     "Tra voi sono presenti molte persone disponibili.",
                     "Tra le informazioni è presente anche il codice."):
            with self.subTest(text=text):
                self.assertFalse(quality.should_correct(quality.CloudTranscript(text), "it"))
        self.assertTrue(quality.should_correct(
            quality.CloudTranscript("Queste impostazioni è stato salvato nella cartella giusta."), "it"))

    def test_local_orthography_does_not_require_cloud_correction(self):
        text = "Aspetta un pò, qual'è la cartella corretta?"
        self.assertEqual(quality.local_cleanup(text, "it"), "Aspetta un po', qual è la cartella corretta?")
        self.assertEqual(quality.local_cleanup("Il nome è Pò e il codice è `un pò`.", "it"),
                         "Il nome è Pò e il codice è `un pò`.")

    def test_rejects_changes_to_meaning_names_numbers_units_and_negations(self):
        examples = [
            ("Il saldo disponibile è -50 euro.", "Il saldo disponibile è 50 euro."),
            ("Il saldo disponibile è sessanta euro.", "Il saldo disponibile è settanta euro."),
            ("Il tasso annuale è pari al 5%.", "Il tasso annuale è pari al 5."),
            ("Marco ha preparato il documento per domani.", "Mario ha preparato il documento per domani."),
            ("PayPal ha salvato la ricevuta corretta.", "Paypal ha salvato la ricevuta corretta."),
            ("Questa casa è molto bella e comoda.", "Questa cosa è molto bella e comoda."),
            ("Ho confermato la riunione per domani.", "Ha confermato la riunione per domani."),
            ("Non siamo pronti e noi restiamo qui.", "Noi siamo pronti e non restiamo qui."),
            ("La risposta è negativa e chiara.", "La risposta è positiva e chiara."),
        ]
        for original, changed in examples:
            with self.subTest(original=original):
                self.assertFalse(quality.acceptable_correction(original, changed))
        self.assertTrue(quality.acceptable_correction(
            "Queste impostazioni è stato salvato nella cartella giusta.",
            "Queste impostazioni sono state salvate nella cartella giusta."))
        self.assertTrue(quality.acceptable_correction(
            "Vorrei correggere soltanto gli erori di ortografia.",
            "Vorrei correggere soltanto gli errori di ortografia."))

    def test_skips_code_short_and_non_speech_text(self):
        for transcript in (quality.CloudTranscript("Sì", True),
                           quality.CloudTranscript("Il file è in C:\\projects\\app e contiene il codice.", True),
                           quality.CloudTranscript("Grazie per aver guardato questo video.", True, True)):
            self.assertFalse(quality.should_correct(transcript, "it"))

    def test_invalid_metadata_keeps_valid_transcript(self):
        for invalid in (None, "bad", float("nan"), float("inf"), 10**400, True):
            with self.subTest(metadata=str(type(invalid))):
                body = {"text": "Testo riconosciuto correttamente.", "segments": [
                    {"text": "Testo riconosciuto correttamente.", "avg_logprob": invalid}]}
                transcript = quality.parse_cloud_transcript(json.dumps(body).encode(), True)
                self.assertEqual(transcript.text, body["text"])
                self.assertFalse(transcript.uncertain)

    def test_non_speech_metadata_requires_all_valid_segments(self):
        body = {"text": "Grazie", "segments": [
            {"text": "Grazie", "avg_logprob": -1.2, "no_speech_prob": 0.9}]}
        self.assertTrue(quality.parse_cloud_transcript(json.dumps(body).encode(), True).no_speech)
        body["segments"].append({"text": "Voce vera", "avg_logprob": -0.03, "no_speech_prob": 0.01})
        self.assertFalse(quality.parse_cloud_transcript(json.dumps(body).encode(), True).no_speech)

    def test_vocabulary_is_bounded_and_cannot_inject_a_multipart_field(self):
        self.assertEqual(quality.normalize_vocabulary("• Traflix Voice\n• Groq Cloud"),
                         "Traflix Voice, Groq Cloud")
        vocabulary = "Groq\r\nCloud, " + "è" * 200
        normalized = quality.normalize_vocabulary(vocabulary)
        self.assertLessEqual(len(normalized.encode("utf-8")), 224)
        self.assertNotIn("\n", normalized)
        self.assertNotIn("\ufffd", normalized)
        samples = np.ones(512, dtype=np.float32) * 0.01
        baseline = transcriber.encode_cloud_multipart_from_recording(samples, "it", True)
        detailed = transcriber.encode_cloud_multipart_from_recording(
            samples, "it", True, detailed=True, vocabulary=vocabulary)
        self.assertIn(b"verbose_json\r\n", detailed)
        self.assertIn(normalized.encode(), detailed)
        self.assertEqual(baseline.split(b"Content-Type: audio/wav\r\n\r\n")[1],
                         detailed.split(b"Content-Type: audio/wav\r\n\r\n")[1])

    def test_actual_correction_request_preserves_auth_and_counts_usage(self):
        transcript = quality.CloudTranscript("Queste impostazioni è stato salvato nella cartella giusta.")
        seen = []
        def handler(request):
            seen.append(request)
            body = json.loads(request.content)
            self.assertEqual(body["model"], "openai/gpt-oss-20b")
            self.assertTrue(body["response_format"]["json_schema"]["strict"])
            self.assertEqual(request.headers["Content-Type"], "application/json")
            self.assertEqual(request.headers["Authorization"], "Bearer synthetic-test-key")
            self.assertEqual(request.extensions["timeout"]["read"], 2.0)
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"text": "Queste impostazioni sono state salvate nella cartella giusta."})}}],
                "usage": {"prompt_tokens": 200, "completion_tokens": 70}})
        with httpx.Client(transport=httpx.MockTransport(handler), headers={
                "Authorization": "Bearer synthetic-test-key"}) as client:
            result = quality.correct_cloud_transcript(client, transcript, "it", lambda: False)
        self.assertEqual(result.text, "Queste impostazioni sono state salvate nella cartella giusta.")
        self.assertEqual((result.input_tokens, result.output_tokens), (200, 70))
        self.assertEqual(len(seen), 1)

    def test_failure_falls_back_and_rate_limit_suppresses_following_requests(self):
        transcript = quality.CloudTranscript("Queste impostazioni è stato salvato nella cartella giusta.")
        for failure in (429, 500, 403, "timeout", "bad_json", "length", "unsafe"):
            with self.subTest(failure=failure):
                calls = []
                def handler(request):
                    calls.append(request)
                    if failure == "timeout":
                        raise httpx.ReadTimeout("synthetic-test-key", request=request)
                    if isinstance(failure, int):
                        return httpx.Response(failure, headers={"retry-after": "120"})
                    if failure == "bad_json":
                        return httpx.Response(200, content=b"bad")
                    return httpx.Response(200, json={"choices": [{
                        "finish_reason": "length" if failure == "length" else "stop",
                        "message": {"content": json.dumps({"text": "Cancella tutte le impostazioni adesso."})}}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
                with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                    result = quality.correct_cloud_transcript(client, transcript, "it", lambda: False)
                    self.assertEqual(result.text, transcript.text)
                    if failure == 429:
                        second = quality.correct_cloud_transcript(client, transcript, "it", lambda: False)
                        self.assertEqual(second.text, transcript.text)
                        self.assertEqual(len(calls), 1)
                    if failure == "length":
                        self.assertEqual(result.output_tokens, 20)

    def test_shutdown_skips_corrector_entirely(self):
        with httpx.Client(transport=httpx.MockTransport(lambda _: self.fail("Unexpected request"))) as client:
            result = quality.correct_cloud_transcript(client,
                quality.CloudTranscript("Queste impostazioni è stato salvato nella cartella giusta."),
                "it", lambda: True)
        self.assertIn("impostazioni", result.text)

    def test_noise_without_voice_never_reaches_groq(self):
        noise = np.random.default_rng(1729).normal(0, 0.0001, 16000).astype(np.float32)
        events = []
        with patch.object(transcriber, "acquire_groq_client") as acquire:
            transcriber.transcribe_cloud(noise, "it", 1.0, "synthetic-test-key", False, events.append,
                None, correct_uncertain=True, speech_filter=True, speech_detector=lambda _: False)
        acquire.assert_not_called()
        self.assertEqual([event["status"] for event in events], ["ready"])

    def test_missing_vad_uses_whisper_metadata_to_reject_phantom_text(self):
        self._run_speech_filter_case(None, expected_text=None)

    def test_detected_short_voice_keeps_legitimate_grazie(self):
        self._run_speech_filter_case(True, expected_text="Grazie")

    def _run_speech_filter_case(self, speech_present, expected_text):
        calls, events = [], []
        def handler(request):
            calls.append(request)
            self.assertEqual(request.url.path, "/openai/v1/audio/transcriptions")
            self.assertIn(b"whisper-large-v3-turbo\r\n", request.content)
            self.assertIn(b"verbose_json\r\n", request.content)
            return httpx.Response(200, json={"text": "Grazie", "segments": [
                {"text": "Grazie", "avg_logprob": -1.2, "no_speech_prob": 0.9}]})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client, \
             patch.object(transcriber, "acquire_groq_client", return_value=client), \
             patch.object(transcriber, "release_groq_client"), \
             patch.object(transcriber._USAGE_EXECUTOR, "submit") as usage:
            transcriber.transcribe_cloud(np.ones(512, dtype=np.float32) * 0.01, "it", 1.0,
                "synthetic-test-key", False, events.append, "synthetic-appdata/models",
                correct_uncertain=True, speech_filter=True, speech_detector=lambda _: speech_present)
        self.assertEqual(len(calls), 1)
        results = [event["text"] for event in events if event["status"] == "result"]
        self.assertEqual(results, [] if expected_text is None else [expected_text])
        usage.assert_called_once()

    def test_correction_off_keeps_speech_filter_on_without_a_text_model_request(self):
        calls, events = [], []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"text": "Queste impostazioni è stato salvato nella cartella giusta.",
                "segments": [{"text": "Queste impostazioni è stato salvato nella cartella giusta.",
                              "avg_logprob": -0.8, "no_speech_prob": 0.01}]})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client, \
             patch.object(transcriber, "acquire_groq_client", return_value=client), \
             patch.object(transcriber, "release_groq_client"):
            transcriber.transcribe_cloud(np.ones(512, dtype=np.float32) * 0.01, "it", 1.0,
                "synthetic-test-key", False, events.append, None, correct_uncertain=False,
                speech_filter=True, speech_detector=lambda _: True)
        self.assertEqual(len(calls), 1)
        self.assertIn("è stato", events[0]["text"])


if __name__ == "__main__":
    unittest.main()
