import io
import threading
import wave
from types import SimpleNamespace

import numpy as np

from mlx_audio import server
from mlx_audio.server import SpeechRequest, TTSExecutionAdapter

SR = 24000
TEXT = "one two three four five six seven eight nine ten eleven twelve"


def speech(burst=0.6, gap=0.12, gain=0.3, lead=0.4, trail=0.7, bursts=3):
    parts = [np.zeros(int(lead * SR))]
    for _ in range(bursts):
        t = np.arange(int(burst * SR)) / SR
        parts += [np.sin(2 * np.pi * 140 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t) ** 2), np.zeros(int(gap * SR))]
    parts.append(np.zeros(int(trail * SR)))
    x = np.concatenate(parts)
    return (x / np.max(np.abs(x)) * gain).astype(np.float32)


class FakeModel:
    def __init__(self, model_type, outputs):
        self.model_type = model_type
        self.sample_rate = SR
        self.outputs = outputs
        self.calls = 0
        self.speeds = []

    def generate(self, text, **kwargs):
        self.speeds.append(kwargs.get("speed"))
        audio = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        yield SimpleNamespace(audio=audio, sample_rate=SR)


class FakeRequest:
    def __init__(self, **fields):
        self.payload = SimpleNamespace(request=SpeechRequest(model="fake", input=TEXT, response_format="wav", **fields))
        self.cancel_event = threading.Event()
        self.emitted = []
        self.done = False

    def emit_data(self, data):
        self.emitted.append(data)

    def emit_done(self):
        self.done = True

    def emit_error(self, error):
        raise error


def run(model, **fields):
    adapter = TTSExecutionAdapter()
    adapter._get_model_for_request = lambda request: model
    request = FakeRequest(**fields)
    adapter.run_serial(request)
    assert request.done and len(request.emitted) == 1
    w = wave.open(io.BytesIO(request.emitted[0]))
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def seconds(x):
    return len(x) / SR


def test_plain_request_is_untouched():
    normal = speech()
    out = run(FakeModel("kokoro", [normal]))
    assert abs(seconds(out) - seconds(normal)) < 0.01


def test_options_trim_level_and_pause_the_response():
    out = run(FakeModel("kokoro", [speech(gain=0.05)]), trim_silence=True, loudness_db=-20, pause_ms=400)
    raw = speech(gain=0.05)
    assert seconds(out) < seconds(raw)  # edge silence trimmed (minus the 0.4s pause added back)
    assert np.all(out[-int(SR * 0.4) + 10 :] == 0)  # fixed pause at the end
    voiced = out[np.abs(out) > 0.02]
    assert 0.05 < np.sqrt(np.mean(voiced**2)) < 0.4  # was 0.05-gain audio; now near -20 dBFS


def test_speed_is_applied_for_models_that_ignore_it_but_not_twice_for_others():
    normal = speech()
    ignores = run(FakeModel("qwen3_tts", [normal]), speed=1.5)
    assert abs(seconds(ignores) - seconds(normal) / 1.5) < 0.1
    native = run(FakeModel("kokoro", [normal]), speed=1.5)
    assert abs(seconds(native) - seconds(normal)) < 0.01  # the model handles it itself


def test_runaway_chunk_is_regenerated_for_a_narration():
    normal = speech()
    dragged = speech(burst=6.0, gap=0.3)  # the same words spread over ~20 seconds
    run(FakeModel("qwen3_tts", [normal]), narration_id="srv-runaway", trim_silence=True)  # sets the pace
    model = FakeModel("qwen3_tts", [dragged, dragged, normal])
    out = run(model, narration_id="srv-runaway", trim_silence=True)
    assert model.calls == 3, model.calls
    assert seconds(out) < 5, seconds(out)  # got the good one, not the dragged one


def test_runaway_retries_are_bounded_and_only_for_narrations():
    dragged = speech(burst=6.0, gap=0.3)
    model = FakeModel("qwen3_tts", [dragged])
    run(model, narration_id="srv-bounded", trim_silence=True)
    assert model.calls == 1 + TTSExecutionAdapter._MAX_RUNAWAY_RETRIES  # gave up, still returned audio
    plain = FakeModel("qwen3_tts", [dragged])
    run(plain)  # no narration_id: never retried
    assert plain.calls == 1


def test_when_every_attempt_is_bad_the_least_bad_one_is_used():
    worst = speech(burst=9.0, gap=0.3)  # ~28s for the words
    bad = speech(burst=5.0, gap=0.3)  # ~16s: still too slow, but the least slow
    model = FakeModel("qwen3_tts", [worst, bad, worst])
    out = run(model, narration_id="srv-leastbad", trim_silence=True)
    assert model.calls == 3
    assert 12 < seconds(out) < 20, seconds(out)  # the middle attempt, not the last one


def test_processing_errors_never_fail_the_request():
    model = FakeModel("kokoro", [speech()])
    adapter = TTSExecutionAdapter()
    adapter._get_model_for_request = lambda request: model
    original = server.polish_audio
    server.polish_audio = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        request = FakeRequest(trim_silence=True)
        adapter.run_serial(request)
        assert request.done and len(request.emitted) == 1  # fell back to the raw audio
    finally:
        server.polish_audio = original
