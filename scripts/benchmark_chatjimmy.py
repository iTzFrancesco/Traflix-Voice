#!/usr/bin/env python3
"""Opt-in live cleanup probe using invented text only, without credentials."""

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))
from whisper_engine import cloud_quality as quality  # noqa: E402


CASES = [
    ("names_and_grammar", "Uso traffic vice con grock per dettare, le impostazioni è corrette.",
     "Uso Traflix Voice con Groq per dettare, le impostazioni sono corrette."),
    ("product_name", "Apri traffic vice e salva il documento.",
     "Apri Traflix Voice e salva il documento."),
    ("agreement", "Queste impostazioni è stato salvato nella cartella giusta.",
     "Queste impostazioni sono state salvate nella cartella giusta."),
    ("spelling", "Vorrei correggere soltanto gli erori di ortografia.",
     "Vorrei correggere soltanto gli errori di ortografia."),
    ("numbers_negation_name", "Non inviare i 250 euro a Marco.",
     "Non inviare i 250 euro a Marco."),
    ("signed_amount", "Il saldo disponibile è -50 euro e non va modificato.",
     "Il saldo disponibile è -50 euro e non va modificato."),
    ("wispr_flow", "Vorrei provare whisper flow nel progetto.",
     "Vorrei provare Wispr Flow nel progetto."),
    ("already_correct", "Uso Traflix Voice con Groq per dettare.",
     "Uso Traflix Voice con Groq per dettare."),
]
VOCABULARY = "Traflix Voice\nGroq\nWispr Flow"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--interval", type=float, default=3.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10:
        parser.error("Use 1 to 10 rounds")
    if not 0.25 <= args.interval <= 60:
        parser.error("Use an interval between 0.25 and 60 seconds")
    if args.output.resolve().is_relative_to(REPO_ROOT):
        parser.error("Keep reports outside the repository")
    rows = []
    current = {}

    def capture_request(_request):
        current["requested"] = True

    def capture_response(response):
        response.read()
        current["http_status"] = response.status_code
        current["candidate"] = response.text.split("<|stats|>", 1)[0].strip()

    with httpx.Client(event_hooks={"request": [capture_request], "response": [capture_response]},
                      limits=httpx.Limits(max_connections=2, max_keepalive_connections=1,
                                         keepalive_expiry=300)) as client:
        for round_index in range(args.rounds):
            for name, original, expected in CASES:
                current = {"case": name, "round": round_index + 1, "requested": False}
                local_text = quality.apply_personal_vocabulary(quality.local_cleanup(original, "it"), VOCABULARY)
                cpu_started, started = time.process_time(), time.perf_counter()
                result = quality.correct_cloud_transcript(
                    client, quality.CloudTranscript(original, True), "it", lambda: False, VOCABULARY)
                current.update(total_ms=round((time.perf_counter() - started) * 1000, 2),
                               cpu_ms=round((time.process_time() - cpu_started) * 1000, 2),
                               output=result.text, expected=expected,
                               vocabulary_output=local_text,
                               llm_changed=result.text != local_text,
                               correct=result.text == expected,
                               changed=result.text != original)
                current["rejected"] = (current.get("http_status") == 200
                                       and current.get("candidate") not in (None, local_text)
                                       and result.text == local_text)
                rows.append(current)
                print(json.dumps(current, ensure_ascii=True), flush=True)
                if current.get("http_status") == 429:
                    break
                time.sleep(args.interval)
            if current.get("http_status") == 429:
                break
    elapsed = [row["total_ms"] for row in rows if row.get("http_status") == 200]
    successful = [row for row in rows if row.get("http_status") == 200]
    summary = {"requests": sum(row["requested"] for row in rows), "trials": len(rows),
               "planned_trials": args.rounds * len(CASES),
               "aborted_on_rate_limit": current.get("http_status") == 429,
               "http_200": len(successful),
               "http_errors": sum(row["requested"] and row.get("http_status") != 200 for row in rows),
               "skipped": sum(not row["requested"] for row in rows),
               "exact_expected_http_200": sum(row["correct"] for row in successful),
               "rejected": sum(row["rejected"] for row in rows),
               "median_ms": statistics.median(elapsed) if elapsed else None,
               "min_ms": min(elapsed) if elapsed else None,
               "max_ms": max(elapsed) if elapsed else None,
               "first_request_ms": rows[0]["total_ms"],
               "median_cpu_ms": statistics.median(row["cpu_ms"] for row in successful) if successful else None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2,
                                      ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "report": str(args.output)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
