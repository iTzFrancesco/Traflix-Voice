SAMPLE_RATE = 16000
# 32 ms keeps the meter and stop response responsive. The lightweight queue
# and throttled volume calculation keep the extra callback rate inexpensive.
BLOCK_SIZE = 512
TRANSCRIPTION_TIMEOUT = 60
GROQ_MODEL = "whisper-large-v3-turbo"
GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MULTIPART_BOUNDARY = "------------------------traflix-voice-8c4e9b"

# Meter calibration shared by every audio block. Keeping the thresholds in dB
# makes the reported value independent from the number of samples in a block.
VOLUME_FLOOR_DB = -58.0
VOLUME_CEILING_DB = -12.0
CLOUD_SILENCE_THRESHOLD = 0.003
CLOUD_SILENCE_PADDING_SECONDS = 0.16
