import numpy as np

from mlx_audio import audio_polish as ap

SR = 24000


def speechlike(
    f0=140.0, gain=0.3, lead=0.5, trail=0.9, bursts=((0.5, 0.15), (0.4, 0.15), (0.6, 0.0)), sr=SR
):
    """Voiced bursts (harmonics with a syllable-like envelope) separated by pauses."""
    parts = [np.zeros(int(lead * sr))]
    for dur, gap in bursts:
        t = np.arange(int(dur * sr)) / sr
        voiced = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 6))
        env = 0.6 + 0.4 * np.sin(2 * np.pi * 4 * t) ** 2  # ~4 syllables per second
        fade = np.minimum(1, np.minimum(t, dur - t) / 0.02)
        parts += [voiced * env * fade, np.zeros(int(gap * sr))]
    parts.append(np.zeros(int(trail * sr)))
    x = np.concatenate(parts)
    return (x / np.max(np.abs(x)) * gain).astype(np.float32)


def f0_of(x, sr=SR):
    fl = int(0.04 * sr)
    lo, hi = int(sr / 300), int(sr / 70)
    vals = []
    for i in range(0, len(x) - fl, int(0.02 * sr)):
        f = x[i : i + fl] - x[i : i + fl].mean()
        if np.sqrt(np.mean(f**2)) < 0.02:
            continue
        ac = np.correlate(f, f, "full")[fl - 1 :]
        ac = ac / ac[0]
        p = int(np.argmax(ac[lo:hi]))
        if ac[lo + p] > 0.5:
            vals.append(sr / (lo + p))
    return float(np.median(vals))


def voiced_rms_db(x):
    mask = ap._voiced_mask(ap._frame_rms(x, SR), 0.1)
    fl = int(ap.FRAME_S * SR)
    v = np.concatenate([x[i * fl : (i + 1) * fl] for i in np.flatnonzero(mask)])
    return 20 * np.log10(np.sqrt(np.mean(v**2)))


def test_noop_when_nothing_requested():
    x = speechlike()
    y = ap.polish_audio(x, SR, text="one two three four five six")
    assert y.shape == x.shape and np.allclose(x, y)


def test_trim_silence_removes_edges_but_keeps_speech():
    x = speechlike(lead=0.5, trail=0.9)
    y = ap.polish_audio(x, SR, text="a b c d e f", trim_silence=True)
    removed = (len(x) - len(y)) / SR
    assert removed > 1.0, removed  # ~1.4s of edge silence minus small pads
    assert len(y) / SR > 1.5  # the speech itself (1.5s) is intact
    # only a short pad of silence remains at each end
    lead = np.argmax(np.abs(y) > 0.01) / SR
    trail = (len(y) - 1 - np.max(np.flatnonzero(np.abs(y) > 0.01))) / SR
    assert lead < 0.12 and trail < 0.15, (lead, trail)


def test_loudness_hits_target_and_never_clips():
    for gain in (0.02, 0.3, 0.9):
        y = ap.polish_audio(speechlike(gain=gain), SR, text="a b c d e f", loudness_db=-20.0)
        assert abs(voiced_rms_db(y) - (-20.0)) < 1.0, (gain, voiced_rms_db(y))
        assert np.max(np.abs(y)) < 1.0


def test_loudness_evens_out_quiet_and_loud_chunks():
    quiet = ap.polish_audio(speechlike(gain=0.05), SR, text="a b c d e f", loudness_db=-20.0)
    loud = ap.polish_audio(speechlike(gain=0.8), SR, text="a b c d e f", loudness_db=-20.0)
    assert abs(voiced_rms_db(quiet) - voiced_rms_db(loud)) < 1.0


def test_pause_is_appended_exactly():
    x = speechlike()
    y = ap.polish_audio(x, SR, text="a b c d e f", pause_ms=500)
    assert len(y) == len(x) + int(SR * 0.5)
    assert np.all(y[-int(SR * 0.5) :] == 0)


def test_time_stretch_changes_duration_and_keeps_pitch():
    x = speechlike()
    for factor in (0.8, 1.25, 1.5):
        y = ap.time_stretch(x, SR, factor)
        assert abs(len(y) / len(x) - 1 / factor) < 0.03, (factor, len(y) / len(x))
        assert np.isfinite(y).all()
        assert abs(f0_of(y) / f0_of(x) - 1) < 0.03, (factor, f0_of(x), f0_of(y))


def test_time_stretch_handles_silence_and_tiny_input():
    assert np.isfinite(ap.time_stretch(np.zeros(SR, np.float32), SR, 1.3)).all()
    tiny = np.ones(100, np.float32)
    assert ap.time_stretch(tiny, SR, 1.5) is tiny


def test_speed_applied_only_when_model_ignores_it():
    x = speechlike()
    ignored = ap.polish_audio(x, SR, text="a b c d e f", speed=1.5, speed_supported=False)
    assert abs(len(ignored) / len(x) - 1 / 1.5) < 0.03
    native = ap.polish_audio(x, SR, text="a b c d e f", speed=1.5, speed_supported=True)
    assert len(native) == len(x)  # the model already did it; do not do it twice


def test_pace_matching_makes_chunks_share_the_first_chunk_pace():
    text = "one two three four five six seven eight nine ten eleven twelve"
    first = speechlike(bursts=((0.7, 0.1), (0.7, 0.1), (0.7, 0.0)))  # slower delivery
    faster = speechlike(bursts=((0.55, 0.1), (0.55, 0.1), (0.55, 0.0)))  # same words, faster
    kw = dict(text=text, trim_silence=True, narration_id="test-pace-1")
    a = ap.polish_audio(first, SR, **kw)
    b_raw = ap.trim_silence_edges(faster, SR)
    b = ap.polish_audio(faster, SR, **kw)
    ra, rb_raw, rb = (ap.articulation_rate(z, SR, text) for z in (a, b_raw, b))
    assert abs(rb_raw / ra - 1) > 0.15  # they really were different
    assert abs(rb / ra - 1) < 0.06, (ra, rb_raw, rb)


def test_pace_correction_is_limited():
    text = "one two three four five six seven eight nine ten eleven twelve"
    slow = speechlike(bursts=((1.2, 0.1), (1.2, 0.1), (1.2, 0.0)))
    fast = speechlike(bursts=((0.3, 0.1), (0.3, 0.1), (0.3, 0.0)))
    ap.polish_audio(slow, SR, text=text, trim_silence=True, narration_id="test-pace-2")
    out = ap.polish_audio(fast, SR, text=text, trim_silence=True, narration_id="test-pace-2")
    trimmed = ap.trim_silence_edges(fast, SR)
    # asked to slow it by 4x, but at most +-20% is applied
    assert len(out) / len(trimmed) < 1.0 / (1 - ap.MAX_PACE_CORRECTION) + 0.05


def test_speed_with_narration_sets_the_reference_for_later_chunks():
    text = "one two three four five six seven eight nine ten eleven twelve"
    x = speechlike()
    a = ap.polish_audio(x, SR, text=text, speed=1.2, speed_supported=False, narration_id="test-pace-3")
    b = ap.polish_audio(x, SR, text=text, speed=1.2, speed_supported=False, narration_id="test-pace-3")
    assert abs(len(a) / len(x) - 1 / 1.2) < 0.03
    assert abs(len(b) / len(a) - 1) < 0.05  # identical input -> identical pace


def test_session_registry_is_bounded():
    for i in range(ap.MAX_SESSIONS + 20):
        ap._set_ref(f"s{i}", 2.5)
    assert len(ap._pace_refs) <= ap.MAX_SESSIONS
    assert ap._get_ref("s0") is None and ap._get_ref(f"s{ap.MAX_SESSIONS + 19}") == 2.5


def test_long_pauses_are_capped_but_short_ones_and_edges_are_not():
    x = speechlike(lead=0.5, trail=0.9, bursts=((0.5, 1.2), (0.4, 0.25), (0.6, 0.0)))
    y = ap.polish_audio(x, SR, text="a b c d e f", max_pause_ms=500)
    removed = (len(x) - len(y)) / SR
    assert 0.55 < removed < 0.8, removed  # the 1.2s pause became ~0.5s; the 0.25s one is untouched
    assert np.isfinite(y).all()
    # edges are not touched by this option (that is trim_silence's job)
    assert abs(np.argmax(np.abs(y) > 0.01) / SR - 0.5) < 0.05


def test_looks_runaway_flags_speech_far_slower_than_the_narration():
    text = "one two three four five six seven eight nine ten eleven twelve"
    normal = speechlike(bursts=((0.6, 0.12), (0.6, 0.12), (0.6, 0.0)))
    ap.polish_audio(normal, SR, text=text, trim_silence=True, narration_id="test-runaway")
    dragged = speechlike(bursts=((6.0, 0.3), (6.0, 0.3), (6.0, 0.0)))  # same words over ~18s
    assert ap.looks_runaway(dragged, SR, text, "test-runaway")
    assert not ap.looks_runaway(normal, SR, text, "test-runaway")


def test_looks_runaway_has_an_absolute_floor_for_a_first_chunk():
    text = "one two three four five six seven eight nine ten eleven twelve"
    dragged = speechlike(bursts=((6.0, 0.3), (6.0, 0.3), (6.0, 0.0)))
    assert ap.looks_runaway(dragged, SR, text, None)
    assert not ap.looks_runaway(speechlike(), SR, text, None)


def test_mildly_slow_chunk_is_stretched_not_cut():
    text = "one two three four five six seven eight nine ten eleven twelve"
    fast = speechlike(bursts=((0.5, 0.1), (0.5, 0.1), (0.5, 0.0)))
    slowish = speechlike(bursts=((0.65, 0.1), (0.65, 0.1), (0.65, 0.0)))  # ~25% slower
    ap.polish_audio(fast, SR, text=text, trim_silence=True, narration_id="test-mild")
    out = ap.polish_audio(slowish, SR, text=text, trim_silence=True, narration_id="test-mild")
    assert len(out) / SR > 1.5 * 0.85  # essentially all the speech kept (then sped up a bit)
