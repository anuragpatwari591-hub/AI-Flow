"""Beat/tempo analysis for authorised audio files (FFmpeg decode + numpy onset detection)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np

SR = 22050
HOP = 512
NFFT = 1024


def decode_mono(path: Path, seconds: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "s16le"]
    if seconds:
        cmd += ["-t", str(seconds)]
    r = subprocess.run(cmd + ["-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def onset_envelope(y: np.ndarray) -> np.ndarray:
    win = np.hanning(NFFT).astype(np.float32)
    n = 1 + (len(y) - NFFT) // HOP
    if n < 4:
        return np.zeros(1, dtype=np.float32)
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(y[idx] * win, axis=1))
    mag = np.log1p(30 * mag)
    flux = np.maximum(mag[1:] - mag[:-1], 0).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    return (flux - flux.mean()) / (flux.std() + 1e-9)


def estimate_beats(env: np.ndarray, bpm_range: tuple[float, float] = (60, 180)) -> tuple[float, list[float], float]:
    fps = SR / HOP
    if len(env) < fps * 2:
        return 0.0, [], 0.0
    k = np.exp(-0.5 * (np.arange(-4, 5) / 1.5) ** 2)
    env = np.convolve(env, k / k.sum(), mode="same")
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    ac = ac / (len(env) - np.arange(len(ac)))  # unbiased: don't favour short lags by overlap
    lags = np.arange(len(ac))
    lo, hi = int(fps * 60 / bpm_range[1]), int(fps * 60 / bpm_range[0])
    seg = ac[lo:hi + 1]
    # weak prior toward 90-140 bpm to reduce octave errors
    bpms = 60 * fps / lags[lo:hi + 1]
    prior = np.exp(-0.5 * ((np.log2(bpms / 115)) / 0.9) ** 2)
    best = lo + int(np.argmax(seg * prior))
    period = float(best)
    # refine with parabolic interpolation
    if 0 < best < len(ac) - 1:
        a, b, c = ac[best - 1], ac[best], ac[best + 1]
        den = a - 2 * b + c
        if den != 0:
            period = best + 0.5 * (a - c) / den
    bpm = 60 * fps / period
    # best phase
    grid = np.arange(0, len(env), period)
    scores = []
    steps = int(period)
    for ph in range(max(steps, 1)):
        pos = np.round(grid[grid + ph < len(env) - 1] + ph).astype(int)
        scores.append(env[pos].sum())
    phase = int(np.argmax(scores))
    pos = np.arange(phase, len(env), period)
    beats = [round(float(p / fps), 3) for p in pos]
    strength = float(np.max(scores) / (np.abs(env).sum() / max(period, 1) + 1e-9))
    return float(bpm), beats, min(strength / 4, 1.0)


def analyze_audio(path: Path, max_seconds: float = 90) -> dict[str, Any]:
    y = decode_mono(path, max_seconds)
    env = onset_envelope(y)
    bpm, beats, conf = estimate_beats(env)
    return {"bpm": round(bpm, 1), "beats": beats, "confidence": round(conf, 2), "duration_s": round(len(y) / SR, 2),
            "method": "log-spectral-flux autocorrelation (estimate, not ground truth)"}
