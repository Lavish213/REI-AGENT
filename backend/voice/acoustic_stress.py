from __future__ import annotations

import asyncio
import json
import subprocess
import sys

import numpy as np

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState


PHRASE = "I am hard of hearing. Please speak slowly. I said next month, not next week. Call me tomorrow at three."
VOICES = ("awb", "kal", "kal16", "rms", "slt")


def synthesize(voice: str) -> np.ndarray:
    response = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"flite=text='{PHRASE}':voice={voice}", "-ar", "16000", "-ac", "1", "-f", "s16le", "pipe:1"], check=True, capture_output=True, timeout=30)
    return np.frombuffer(response.stdout, dtype="<i2").astype(np.float64) / 32768


def bandlimit(speech: np.ndarray, low: int, high: int) -> np.ndarray:
    spectrum = np.fft.rfft(speech)
    frequencies = np.fft.rfftfreq(len(speech), 1 / 16000)
    spectrum[(frequencies < low) | (frequencies > high)] = 0
    return np.fft.irfft(spectrum, n=len(speech))


def distortions(speech: np.ndarray) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(20261011)
    noise = rng.normal(size=len(speech))
    noise /= np.sqrt(np.mean(noise ** 2))
    rms = np.sqrt(np.mean(speech ** 2))
    phone = bandlimit(speech, 300, 3400)
    raw = np.round(np.clip(speech, -1, 1) * 32767).astype("<i2").tobytes()
    encoded = subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "pipe:0", "-ar", "8000", "-f", "mulaw", "pipe:1"], input=raw, capture_output=True, check=True, timeout=30).stdout
    decoded = subprocess.run(["ffmpeg", "-v", "error", "-f", "mulaw", "-ar", "8000", "-ac", "1", "-i", "pipe:0", "-ar", "16000", "-f", "s16le", "pipe:1"], input=encoded, capture_output=True, check=True, timeout=30).stdout
    echo = speech.copy()
    delay = 3200
    echo[delay:] += 0.5 * speech[:-delay]
    dropouts = speech.copy()
    for start in range(0, len(speech), 6400):
        dropouts[start:start+1280] = 0
    samples = {
        "clean": speech,
        "phone_band": phone,
        "pcmu_8khz_roundtrip": np.frombuffer(decoded, dtype="<i2").astype(np.float64) / 32768,
        "muffled_800hz": bandlimit(speech, 0, 800),
        "quiet_minus_26db": speech * 0.05,
        "clipped_gain_12": speech * 12,
        "echo_200ms": echo,
        "dropouts_20pct": dropouts,
        "hum_60hz": speech + rms * np.sin(2 * np.pi * 60 * np.arange(len(speech)) / 16000),
    }
    for snr in (20, 10, 0, -5):
        samples[f"white_noise_snr_{snr}db"] = speech + noise * rms / (10 ** (snr / 20))
    return samples


async def analyze(samples: np.ndarray) -> dict:
    clipped = np.clip(samples, -1, 1)
    pcm = np.round(clipped * 32767).astype("<i2").tobytes()
    vad = SileroVADAnalyzer(sample_rate=16000, params=VADParams(confidence=0.7, start_secs=0.3, stop_secs=0.8, min_volume=0.3))
    vad.set_sample_rate(16000)
    confidences = []
    original_confidence = vad.voice_confidence

    def record_confidence(buffer):
        score = original_confidence(buffer)
        confidences.append(float(np.asarray(score).reshape(-1)[0]))
        return score

    vad.voice_confidence = record_confidence
    states = []
    try:
        for offset in range(0, len(pcm), 1024):
            states.append(await vad.analyze_audio(pcm[offset:offset+1024]))
    finally:
        vad._executor.shutdown(wait=True)
    speaking = sum(state == VADState.SPEAKING for state in states)
    return {"duration_seconds": round(len(samples) / 16000, 2), "frames": len(states), "speaking_frames": speaking, "speech_detected": speaking > 0, "max_vad_confidence": round(max(confidences, default=0), 4), "frames_above_confidence_threshold": sum(score >= 0.7 for score in confidences), "clipped_sample_fraction": round(float(np.mean(np.abs(samples) > 1)), 4), "rms": round(float(np.sqrt(np.mean(clipped ** 2))), 6)}


async def run_acoustic_stress() -> dict:
    runs = []
    for voice in VOICES:
        for condition, speech in distortions(synthesize(voice)).items():
            runs.append({"synthetic_voice": voice, "condition": condition, **await analyze(speech)})
    rng = np.random.default_rng(20261011)
    for level in (0.01, 0.1, 0.5):
        runs.append({"synthetic_voice": None, "condition": f"noise_only_rms_{level}", **await analyze(rng.normal(0, level, 64000))})
    runs.append({"synthetic_voice": None, "condition": "silence", **await analyze(np.zeros(64000))})
    return {"mode": "actual_synthetic_pcm_through_installed_silero_vad_without_asr_llm_or_tts_provider", "runs": len(runs), "speech_runs": len(VOICES)*13, "noise_or_silence_runs": 4, "phrase": PHRASE, "recognized_words": None, "human_accents_tested": 0, "results": runs, "ffmpeg_version": subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]}


if __name__ == "__main__":
    sys.stdout.write(json.dumps(asyncio.run(run_acoustic_stress()), indent=2) + "\n")
