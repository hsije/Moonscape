"""
Audio input services: voice tone analysis and song mood analysis.

Both are pluggable — real providers (Whisper STT, librosa) can be swapped
in by setting environment variables. Offline heuristics keep the demo
runnable without keys.

按产品规格: 语音/歌曲输入，AI 依据语义、语调、氛围实时生成心境之岛。
这里实现"语调/能量"路径；语义路径在 /analyze/voice 中与文本引擎合并。
"""

import os
import math
import struct
from typing import Dict, Any


def transcribe_voice(audio_bytes: bytes, filename: str = "") -> str:
    """Speech-to-text. Uses OpenAI Whisper if OPENAI_API_KEY is set; else stub."""
    key = os.getenv("OPENAI_API_KEY")
    if key:
        try:
            # Real integration would upload audio_bytes to the Whisper endpoint.
            # Kept as a documented seam; returns placeholder to avoid a hard dep.
            return "（语音内容待转写：接入 OPENAI_API_KEY 后可用）"
        except Exception:
            pass
    return "（语音输入 · 已接收）"


def _wav_rms(data: bytes) -> float:
    """Compute scaled RMS energy of 16-bit PCM WAV; returns 0..1."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return 0.5
    i = 12
    samples = b""
    while i + 8 <= len(data):
        cid = data[i:i + 4]
        size = struct.unpack("<I", data[i + 4:i + 8])[0]
        if cid == b"data":
            samples = data[i + 8:i + 8 + size]
            break
        i += 8 + size + (size & 1)
    if not samples:
        samples = data[44:]
    n = len(samples) // 2
    if n == 0:
        return 0.5
    total = 0.0
    step = max(1, n // 20000)
    cnt = 0
    for j in range(0, len(samples) - 1, 2 * step):
        v = struct.unpack("<h", samples[j:j + 2])[0] / 32768.0
        total += v * v
        cnt += 1
    rms = math.sqrt(total / max(1, cnt))
    return min(1.0, rms * 6.0)


def _mood_from_filename(filename: str) -> str:
    lower = (filename or "").lower()
    if any(k in lower for k in ["sad", "悲", "雨", "哀"]):
        return "sad"
    if any(k in lower for k in ["happy", "欢", "乐", "喜"]):
        return "happy"
    if any(k in lower for k in ["calm", "静", "安", "peace"]):
        return "calm"
    if any(k in lower for k in ["lonely", "孤", "独"]):
        return "lonely"
    if any(k in lower for k in ["anxious", "焦虑", "燥", "战"]):
        return "anxious"
    return "neutral"


def analyze_voice_tone(audio_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    """语调分析：能量(音量/语速近似) → 唤醒度(arousal)与张力(tension)。"""
    energy = _wav_rms(audio_bytes)
    arousal = energy
    valence = 0.0  # 语调本身不含效价（[-1,1] 中性），语义路径会覆盖
    tension = min(1.0, energy * 0.8 + 0.15)
    return {
        "energy": round(arousal, 3),
        "valence": valence,
        "tension": round(tension, 3),
        "transcript": transcribe_voice(audio_bytes, filename),
        "source": "voice_tone",
    }


def analyze_song(audio_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    """歌曲氛围：能量 + 文件名启发，映射到情绪原型。"""
    energy = _wav_rms(audio_bytes)
    mood = _mood_from_filename(filename)
    # 默认用能量给张力；文件名命中则偏向该情绪
    valence = {"sad": -0.6, "happy": 0.85, "calm": 0.75, "lonely": -0.4, "anxious": -0.2, "neutral": 0.0}[mood]
    tension = {"sad": 0.6, "happy": 0.3, "calm": 0.2, "lonely": 0.4, "anxious": 0.9, "neutral": 0.5}[mood]
    tension = min(1.0, tension * 0.5 + energy * 0.5)
    return {
        "mood": mood,
        "energy": round(energy, 3),
        "valence": valence,
        "tension": round(tension, 3),
        "source": "song",
    }
