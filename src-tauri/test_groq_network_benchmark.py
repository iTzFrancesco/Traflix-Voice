"""Protect the live benchmark's production equivalence and numeric-only output."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))
spec = importlib.util.spec_from_file_location(
    "groq_network_benchmark", REPO_ROOT / "scripts" / "benchmark_groq_network.py"
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class GroqNetworkBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.samples = (np.sin(np.arange(16000, dtype=np.float32) * 0.08) * 0.01).astype(np.float32)

    def test_baseline_request_matches_production_transcription(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, text="synthetic transcript")

        with httpx.Client(transport=httpx.MockTransport(respond),
                          headers={"Authorization": "Bearer placeholder"}) as client:
            row = benchmark.measure(client, self.samples, "it", "baseline")
            prepared = self.samples.copy()
            benchmark.audio.apply_automatic_gain(prepared)
            events = []
            with patch.object(benchmark.transcriber, "acquire_groq_client", return_value=client), \
                    patch.object(benchmark.transcriber, "release_groq_client"):
                benchmark.transcriber.transcribe_cloud(
                    prepared, "it", 1.0, "placeholder", False, events.append, None
                )
        self.assertTrue(row["success"])
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].content, requests[1].content)
        self.assertEqual(requests[0].headers, requests[1].headers)
        self.assertEqual(requests[0].url, requests[1].url)
        self.assertEqual([event["status"] for event in events], ["result"])
        self.assertEqual(row["transcript_characters"], len("synthetic transcript"))
        self.assertNotIn("synthetic transcript", json.dumps(row))

    def test_trace_records_durations_without_recording_info(self):
        def respond(request):
            trace = request.extensions["trace"]
            trace("connection.connect_tcp.started", {"secret": "private trace content"})
            trace("connection.connect_tcp.complete", {"secret": "private trace content"})
            trace("http11.receive_response_headers.started", {"request": request})
            trace("http11.receive_response_headers.complete", {"headers": request.headers})
            return httpx.Response(200, text="private transcript", headers={"Private": "private header"})

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            row = benchmark.measure(client, self.samples, "it", "baseline")
        self.assertTrue(row["success"])
        self.assertTrue(row["new_connection"])
        self.assertGreaterEqual(row["connect_ms"], 0)
        self.assertGreaterEqual(row["response_wait_ms"], 0)
        self.assertNotIn("private", json.dumps(row))

    def test_rate_limit_response_is_a_failure_without_body_or_headers(self):
        with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
                429, text="private error response", headers={"Private": "private header"}))) as client:
            row = benchmark.measure(client, self.samples, "it", "baseline")
        self.assertFalse(row["success"])
        self.assertEqual(row["http_status"], 429)
        self.assertNotIn("private", json.dumps(row))
        self.assertNotIn("total_ms", benchmark.summarize([dict(row, warmup=False)]))

    def test_transport_exception_does_not_expose_the_message(self):
        def respond(_request):
            raise httpx.ConnectError("private credential in exception")

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            row = benchmark.measure(client, self.samples, "it", "baseline")
        self.assertFalse(row["success"])
        self.assertEqual(row["error_type"], "ConnectError")
        self.assertNotIn("private", json.dumps(row))

    def test_cli_stops_at_first_rate_limit_and_saves_partial_numeric_evidence(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(429, text="private provider error")

        with tempfile.TemporaryDirectory() as directory, \
                httpx.Client(transport=httpx.MockTransport(respond)) as client:
            output = Path(directory) / "evidence.json"
            arguments = ["benchmark", "--wav", "synthetic.wav", "--cases", "baseline",
                         "--iterations", "3", "--warmup", "0", "--interval", "0",
                         "--output", str(output)]
            with patch.object(sys, "argv", arguments), \
                    patch.dict(benchmark.os.environ, {"GROQ_API_KEY": "placeholder"}), \
                    patch.object(benchmark, "load_wav", return_value=self.samples), \
                    patch.object(benchmark, "create_client", return_value=client), \
                    redirect_stdout(io.StringIO()):
                exit_code = benchmark.main()
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(requests), 1)
        self.assertEqual(report["request_count"], 1)
        self.assertFalse(report["completed"])
        self.assertEqual(report["rows"][0]["http_status"], 429)
        self.assertNotIn("private", json.dumps(report))
        self.assertNotIn("placeholder", json.dumps(report))

    def test_failed_and_warmup_calls_are_excluded_from_comparisons(self):
        rows = [
            dict(case="baseline", round=0, total_ms=500, success=True, warmup=True),
            dict(case="baseline", round=1, total_ms=100, success=True, warmup=False),
            dict(case="baseline", round=2, total_ms=200, success=True, warmup=False),
            dict(case="baseline", round=3, total_ms=1, success=False, warmup=False),
            dict(case="http2", round=1, total_ms=80, success=True, warmup=False),
            dict(case="http2", round=2, total_ms=210, success=True, warmup=False),
            dict(case="http2", round=3, total_ms=0, success=True, warmup=False),
        ]
        self.assertEqual(benchmark.paired_savings(rows, "http2"),
                         {"pairs": 2, "faster_pairs": 1, "median_saving_ms": 5})
        reference = [dict(row, new_connection=False, http_version="HTTP/1.1")
                     for row in rows if row["case"] == "baseline"]
        summary = benchmark.summarize(reference)
        self.assertEqual(summary["samples"], 2)
        self.assertEqual(summary["failures"], 1)
        self.assertEqual(summary["total_ms"]["median"], 150)
        self.assertEqual(summary["total_ms"]["p95"], 200)

    def test_word_error_rate_ignores_case_and_punctuation_and_counts_missing_words(self):
        self.assertEqual(benchmark.word_error_rate("Hello, WORLD!", "hello world"), 0)
        self.assertEqual(benchmark.word_error_rate("one two three", "one three"), 1 / 3)
        self.assertEqual(benchmark.word_error_rate("one two", "one wrong extra"), 1)

    @unittest.skipUnless(importlib.util.find_spec("soundfile"), "Optional soundfile is not installed")
    def test_flac_preserves_the_exact_pcm_sent_in_wav(self):
        import soundfile

        payload = benchmark.encode_payload(self.samples, "it", "flac")
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: multipart/form-data; boundary="
            + benchmark.transcriber.GROQ_MULTIPART_BOUNDARY.encode("ascii")
            + b"\r\nMIME-Version: 1.0\r\n\r\n" + payload
        )
        file_part = next(part for part in message.iter_parts()
                         if part.get_param("name", header="content-disposition") == "file")
        pcm, sample_rate = soundfile.read(io.BytesIO(file_part.get_payload(decode=True)), dtype="int16")
        np.testing.assert_array_equal(pcm, benchmark.transcriber._encode_pcm16(self.samples, True))
        self.assertEqual(sample_rate, 16000)
        self.assertEqual(file_part.get_filename(), "audio.flac")
        self.assertEqual(file_part.get_content_type(), "audio/flac")

    def test_cold_client_preserves_production_headers_and_timeouts(self):
        with benchmark.create_client("placeholder", "baseline") as baseline, \
                benchmark.create_client("placeholder", "cold") as cold:
            self.assertEqual(cold.headers, baseline.headers)
            self.assertEqual(cold.timeout, baseline.timeout)
            self.assertFalse(cold.follow_redirects)


if __name__ == "__main__":
    unittest.main()
