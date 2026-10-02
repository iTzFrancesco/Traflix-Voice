SAMPLE_RATE = 16000
DEFAULT_LOCAL_MODEL = "parakeet-tdt-0.6b-v3-int8"
PARAKEET_MODEL_ID = "parakeet-tdt-0.6b-v3-int8"
# 32 ms keeps the meter and stop response responsive. The lightweight queue
# and throttled volume calculation keep the extra callback rate inexpensive.
BLOCK_SIZE = 512
TRANSCRIPTION_TIMEOUT = 60
GROQ_MODEL = "whisper-large-v3-turbo"
AUTO_GAIN_TARGET_RMS = 0.08
AUTO_GAIN_ACTIVITY_THRESHOLD = 0.0015
AUTO_GAIN_MAX = 4.0
AUTO_GAIN_PEAK_CEILING = 0.98
GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MULTIPART_BOUNDARY = "------------------------traflix-voice-8c4e9b"

# Meter calibration shared by every audio block. Keeping the thresholds in dB
# makes the reported value independent from the number of samples in a block.
VOLUME_FLOOR_DB = -58.0
VOLUME_CEILING_DB = -12.0
VOLUME_DB_SCALE = 100.0 / (VOLUME_CEILING_DB - VOLUME_FLOOR_DB)
# Trim only audio below one PCM16 quantization step. A volume gate cannot
# distinguish background noise from quiet consonants or whispered words.
CLOUD_SILENCE_THRESHOLD = 1.0 / 32767.0
CLOUD_SILENCE_PADDING_SECONDS = 0.32
# Drain to keep tail after stop (reverberation / weak fricative)
CLOUD_TAIL_DRAIN_SECONDS = 0.22
