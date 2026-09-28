"""Post-processing that makes separately generated speech chunks sound like one narration.

A long text is spoken as many independent chunks, and a sampling TTS model gives each
chunk its own volume, pace and edge silence. ``polish_audio`` evens those out:

* ``trim_silence``  cuts leading/trailing silence so chunk seams are not random.
* ``max_pause_ms``  shortens silences inside the audio that are longer than this, so long
                    hesitations do not make one chunk sound slower than another.
* ``loudness_db``   sets the speech level (RMS of the voiced parts) to a fixed target.
* ``pause_ms``      appends a fixed pause, so the gap between chunks is always the same.
* ``narration_id``  matches the pace (words per second of voiced speech) of every chunk to
                    the first chunk of the same narration, by time-stretching.
* ``looks_runaway`` detects the model occasionally failing to stop, or dragging the text out
                    at a fraction of normal speed; the server regenerates such a chunk.
* ``speed``         a real playback-speed change for models that ignore the ``speed``
                    argument (e.g. Qwen3-TTS), done by pitch-preserving time-stretching.
"""

import threading
from collections import OrderedDict
from typing import Optional

import numpy as np
from scipy.signal import correlate

FRAME_S = 0.02  # analysis frame for level / silence detection
MAX_PACE_CORRECTION = 0.2  # never stretch a chunk by more than +-20% to match the pace
MIN_STRETCH_DELTA = 0.02  # ignore corrections smaller than 2%
RUNAWAY_RATIO = 0.7  # a chunk slower than this fraction of the narration pace is suspect
ABSOLUTE_MIN_RATE = 1.8  # words (or characters) per voiced second below which speech is broken
MAX_SESSIONS = 128

_pace_refs: "OrderedDict[str, float]" = OrderedDict()
_lock = threading.Lock()


def _frame_rms(x: np.ndarray, sr: int) -> np.ndarray:
    fl = max(1, int(FRAME_S * sr))
    n = len(x) // fl
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    frames = x[: n * fl].reshape(n, fl)
    return np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))


def _voiced_mask(rms: np.ndarray, rel: float) -> np.ndarray:
    """Frames louder than ``rel`` x the (95th percentile) speech level."""
    if rms.size == 0:
        return np.zeros(0, dtype=bool)
    ref = np.percentile(rms, 95)
    return rms > max(rel * ref, 1e-5)


def trim_silence_edges(
    x: np.ndarray, sr: int, lead_pad_s: float = 0.04, trail_pad_s: float = 0.08
) -> np.ndarray:
    """Cut leading and trailing silence, keeping a short natural pad."""
    mask = _voiced_mask(_frame_rms(x, sr), 0.03)
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return x
    fl = int(FRAME_S * sr)
    start = max(0, idx[0] * fl - int(lead_pad_s * sr))
    end = min(len(x), (idx[-1] + 1) * fl + int(trail_pad_s * sr))
    y = x[start:end].copy()
    fade = min(int(0.005 * sr), len(y) // 2)
    if fade > 0:  # avoid clicks at the new edges
        ramp = np.linspace(0.0, 1.0, fade, dtype=y.dtype)
        y[:fade] *= ramp
        y[-fade:] *= ramp[::-1]
    return y


def cap_pauses(x: np.ndarray, sr: int, max_pause_s: float) -> np.ndarray:
    """Shorten silences between speech (not at the edges) to at most ``max_pause_s``."""
    mask = _voiced_mask(_frame_rms(x, sr), 0.05)
    idx = np.flatnonzero(mask)
    if idx.size < 2:
        return x
    fl = int(FRAME_S * sr)
    keep = max(1, int(round(max_pause_s / FRAME_S)))
    cuts = []  # (start_frame, end_frame) of the silent frames to remove
    run_start = None
    for f in range(idx[0], idx[-1] + 1):
        if not mask[f]:
            if run_start is None:
                run_start = f
        elif run_start is not None:
            if f - run_start > keep:
                cuts.append((run_start + keep // 2, f - (keep - keep // 2)))
            run_start = None
    if not cuts:
        return x
    pieces, pos = [], 0
    for a, b in cuts:
        pieces.append(x[pos : a * fl])
        pos = b * fl
    pieces.append(x[pos:])
    return np.concatenate(pieces)


def voiced_seconds(x: np.ndarray, sr: int) -> float:
    """Time actually spoken: silences (between words and sentences) are not counted."""
    return float(np.count_nonzero(_voiced_mask(_frame_rms(x, sr), 0.1))) * FRAME_S


def speech_units(text: str) -> int:
    """Words, or characters for scripts written without spaces."""
    t = text.strip()
    return len(t.split()) if " " in t else len(t)


def articulation_rate(x: np.ndarray, sr: int, text: str) -> Optional[float]:
    """Speech units per second of voiced audio, or None if it cannot be measured."""
    seconds = voiced_seconds(x, sr)
    units = speech_units(text)
    if seconds < 0.3 or units < 2:
        return None
    return units / seconds


def set_loudness(x: np.ndarray, sr: int, target_db: float) -> np.ndarray:
    """Scale so the voiced parts have an RMS level of ``target_db`` dBFS."""
    mask = _voiced_mask(_frame_rms(x, sr), 0.1)
    if not mask.any():
        return x
    fl = int(FRAME_S * sr)
    voiced = np.concatenate([x[i * fl : (i + 1) * fl] for i in np.flatnonzero(mask)])
    rms = float(np.sqrt(np.mean(voiced.astype(np.float64) ** 2)))
    if rms < 1e-6:
        return x
    gain = 10 ** (target_db / 20) / rms
    gain = float(np.clip(gain, 10 ** (-24 / 20), 10 ** (24 / 20)))
    y = x * gain
    # soft limiter: keeps peaks below 1.0 without hard clipping
    knee = 0.9
    over = np.abs(y) > knee
    if over.any():
        y[over] = np.sign(y[over]) * (knee + (1 - knee) * np.tanh((np.abs(y[over]) - knee) / (1 - knee)))
    return y.astype(x.dtype, copy=False)


def time_stretch(x: np.ndarray, sr: int, factor: float) -> np.ndarray:
    """Change speed by ``factor`` (>1 is faster) without changing pitch (WSOLA)."""
    if abs(factor - 1.0) < 1e-3 or len(x) < int(0.2 * sr):
        return x
    fl = (int(0.032 * sr) // 2) * 2
    hop = fl // 2
    tol = int(0.012 * sr)
    win = np.hanning(fl + 1)[:fl].astype(np.float64)  # periodic Hann: 50% overlap sums to 1
    src = np.pad(x.astype(np.float64), (tol + fl, tol + 2 * fl))
    base = tol + fl
    n_out = int(len(x) / factor)
    n_frames = n_out // hop + 1
    out = np.zeros(n_frames * hop + fl)
    norm = np.zeros_like(out)
    prev = 0
    for k in range(n_frames):
        target = base + int(round(k * hop * factor))
        if k == 0:
            pos = target
        else:
            ref = src[prev + hop : prev + hop + fl]  # how the previous frame would naturally continue
            cand = src[target - tol : target + tol + fl]
            if len(cand) < fl + 2 * tol or len(ref) < fl:
                pos = target
            else:
                corr = correlate(cand, ref, mode="valid", method="fft")
                pos = target - tol + int(np.argmax(corr))
        seg = src[pos : pos + fl]
        if len(seg) < fl:
            break
        out[k * hop : k * hop + fl] += seg * win
        norm[k * hop : k * hop + fl] += win
        prev = pos
    valid = norm > 1e-3
    out[valid] /= norm[valid]
    return out[:n_out].astype(x.dtype)


def _get_ref(narration_id: str) -> Optional[float]:
    with _lock:
        ref = _pace_refs.get(narration_id)
        if ref is not None:
            _pace_refs.move_to_end(narration_id)
        return ref


def _set_ref(narration_id: str, rate: float) -> None:
    with _lock:
        _pace_refs[narration_id] = rate
        _pace_refs.move_to_end(narration_id)
        while len(_pace_refs) > MAX_SESSIONS:
            _pace_refs.popitem(last=False)


def chunk_pace(audio, sample_rate: int, text: str) -> Optional[float]:
    """Speech units per voiced second of a generated chunk (None if unmeasurable)."""
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim != 1 or x.size == 0:
        return None
    return articulation_rate(trim_silence_edges(x, sample_rate), sample_rate, text)


def looks_runaway(audio, sample_rate: int, text: str, narration_id: Optional[str] = None) -> bool:
    """True if a chunk is far slower than speech should be, so it is worth regenerating.

    Compares against the narration's pace when the first chunk has set one, and
    otherwise against an absolute floor.
    """
    rate = chunk_pace(audio, sample_rate, text)
    if rate is None:
        return False
    if rate < ABSOLUTE_MIN_RATE:
        return True
    ref = _get_ref(narration_id) if narration_id else None
    return ref is not None and rate < RUNAWAY_RATIO * ref


def polish_audio(
    audio,
    sample_rate: int,
    *,
    text: str,
    speed: Optional[float] = 1.0,
    speed_supported: bool = True,
    trim_silence: bool = False,
    max_pause_ms: Optional[int] = None,
    loudness_db: Optional[float] = None,
    pause_ms: int = 0,
    narration_id: Optional[str] = None,
) -> np.ndarray:
    """Apply the requested clean-ups to one generated chunk. Returns float32 mono audio.

    ``speed_supported`` says whether the model already applied ``speed`` itself.
    """
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim != 1 or x.size == 0:
        return x
    speed = float(speed or 1.0)

    if trim_silence:
        x = trim_silence_edges(x, sample_rate)
    if max_pause_ms:
        x = cap_pauses(x, sample_rate, max_pause_ms / 1000)

    # pace: match the first chunk of this narration, or apply the requested speed
    factor = 1.0
    if narration_id:
        rate = articulation_rate(x, sample_rate, text)
        if rate is not None:
            ref = _get_ref(narration_id)
            if ref is None:
                factor = 1.0 if speed_supported else speed
                _set_ref(narration_id, rate * factor)
            else:
                factor = ref / rate
                factor = float(np.clip(factor, 1 - MAX_PACE_CORRECTION, 1 + MAX_PACE_CORRECTION))
        elif not speed_supported:
            factor = speed
    elif not speed_supported:
        factor = speed
    if abs(factor - 1.0) >= MIN_STRETCH_DELTA:
        x = time_stretch(x, sample_rate, factor)

    if loudness_db is not None:
        x = set_loudness(x, sample_rate, float(loudness_db))

    if pause_ms and pause_ms > 0:
        x = np.concatenate([x, np.zeros(int(sample_rate * pause_ms / 1000), dtype=x.dtype)])
    return x.astype(np.float32, copy=False)
