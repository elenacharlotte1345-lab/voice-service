import numpy as np
import wave
import opuslib
import os
from scipy import signal

SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_DURATION_MS = 60
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)   # 960
OPUS_BITRATE = 16000
OPUS_APPLICATION = 2048          # VOIP
OPUS_COMPLEXITY = 5

class AudioProcessor:
    def __init__(self):
        self.encoder = None
        self.decoder = None

    def _init_encoder(self):
        if self.encoder is None:
            self.encoder = opuslib.Encoder(SAMPLE_RATE, CHANNELS, OPUS_APPLICATION)
            self.encoder.bitrate = OPUS_BITRATE
            try:
                self.encoder.complexity = OPUS_COMPLEXITY
            except AttributeError:
                pass

    def _init_decoder(self):
        if self.decoder is None:
            self.decoder = opuslib.Decoder(SAMPLE_RATE, CHANNELS)

    def encode_pcm_to_opus_packets(self, pcm_bytes: bytes):
        self._init_encoder()
        pcm_array = np.frombuffer(pcm_bytes, dtype=np.int16)
        packets = []
        for i in range(0, len(pcm_array), FRAME_SIZE):
            frame = pcm_array[i:i+FRAME_SIZE]
            if len(frame) < FRAME_SIZE:
                frame = np.pad(frame, (0, FRAME_SIZE - len(frame)))
            packets.append(self.encoder.encode(frame.tobytes(), FRAME_SIZE))
        return packets

    def generate_silence_packets(self, count=2):
        self._init_encoder()
        silence_pcm = np.zeros(FRAME_SIZE, dtype=np.int16).tobytes()
        return [self.encoder.encode(silence_pcm, FRAME_SIZE) for _ in range(count)]

    def decode_opus_to_pcm(self, opus_packet: bytes) -> bytes:
        self._init_decoder()
        return self.decoder.decode(opus_packet, FRAME_SIZE)

def convert_audio_to_pcm(file_bytes: bytes, original_filename: str) -> bytes:
    """将任意音频文件转换为 16kHz 单声道 int16 PCM 字节"""
    import tempfile
    import librosa
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(original_filename)[1]) as tmp_in:
        tmp_in.write(file_bytes)
        tmp_in_path = tmp_in.name
    try:
        audio, sr = librosa.load(tmp_in_path, sr=SAMPLE_RATE, mono=True)
        audio_int16 = (audio * 32767).astype(np.int16)
        return audio_int16.tobytes()
    finally:
        os.unlink(tmp_in_path)

def save_pcm_to_wav(pcm_bytes: bytes, filepath: str):
    with wave.open(filepath, 'wb') as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm_bytes)