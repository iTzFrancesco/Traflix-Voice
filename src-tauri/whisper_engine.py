#!/usr/bin/env python3
"""Traflix Voice - Whisper Engine (entry point)"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from whisper_engine.engine import WhisperEngine

if __name__ == "__main__":
    engine = WhisperEngine()
    engine.run()
