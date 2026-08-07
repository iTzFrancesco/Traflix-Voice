SAMPLE_RATE = 16000
# 128 ms keeps stop-to-upload latency low while leaving enough work per audio
# callback for inexpensive NumPy metering.
BLOCK_SIZE = 2048
TRANSCRIPTION_TIMEOUT = 60
GROQ_MODEL = "whisper-large-v3-turbo"

# Meter calibration shared by every audio block. Keeping the thresholds in dB
# makes the reported value independent from the number of samples in a block.
VOLUME_FLOOR_DB = -58.0
VOLUME_CEILING_DB = -12.0
