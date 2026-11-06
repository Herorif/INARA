"""telephony.audio.Resampler: the numpy path against the pure-Python path."""

from array import array
import random

import pytest

from telephony import audio
from telephony.audio import Resampler, tone

np = pytest.importorskip("numpy")

PAIRS = [(48000, 16000), (24000, 48000), (8000, 16000), (16000, 8000), (24000, 8000),
         (44100, 16000), (16000, 24000), (88200, 16000), (24000, 44100)]


def signal(rate, seconds=0.6, seed=0):
    rng = random.Random(seed)
    voiced = array("h", tone(700, seconds, rate, 0.6))
    noisy = array("h", (max(-32768, min(32767, v + int(rng.gauss(0, 3000)))) for v in voiced))
    noisy[: rate // 50] = array("h", [32767, -32768] * (rate // 100))  # clipping-range edges
    return noisy.tobytes()


def chunked(resampler, data, rng):
    out, position = [], 0
    while position < len(data):
        size = 2 * rng.randint(0, 900)
        out.append(resampler.process(data[position : position + size]))
        position += size
    return b"".join(out)


def as_samples(data):
    return np.frombuffer(data, dtype="<i2").astype(np.int32)


@pytest.mark.parametrize("source,target", PAIRS)
def test_numpy_matches_pure_python_across_chunks_and_reset(source, target):
    data = signal(source)
    rng = random.Random(source + target)
    fast = Resampler(source, target, use_numpy=True)
    slow = Resampler(source, target, use_numpy=False)
    assert (fast.backend, slow.backend) == ("numpy", "python")
    assert fast.phases == slow.phases  # the same filter
    for _round in range(2):
        a, b = chunked(fast, data, rng), chunked(slow, data, rng)
        assert len(a) == len(b)
        assert np.abs(as_samples(a) - as_samples(b)).max() <= 1
        assert fast.position == slow.position
        assert list(fast.history) == slow.history  # the same state
        fast.reset()
        slow.reset()
    # Chunked numpy output equals one pass exactly.
    one_pass = Resampler(source, target, use_numpy=True).process(data)
    assert chunked(Resampler(source, target, use_numpy=True), data, random.Random(9)) == one_pass


def test_state_carries_between_chunks_identically():
    data = signal(48000, seconds=0.2)
    fast = Resampler(48000, 16000, use_numpy=True)
    slow = Resampler(48000, 16000, use_numpy=False)
    for size in (2, 4, 6, 1000, 0, 3, 962):
        piece, data = data[: size * 2], data[size * 2 :]
        a, b = fast.process(piece), slow.process(piece)
        assert len(a) == len(b)
        assert fast.position == slow.position


def test_default_picks_numpy_and_falls_back_without_it(monkeypatch):
    assert Resampler(48000, 16000).backend == "numpy"
    monkeypatch.setattr(audio, "_numpy", lambda: None)
    assert Resampler(48000, 16000).backend == "python"
    with pytest.raises(ImportError):
        Resampler(48000, 16000, use_numpy=True)
    assert Resampler(16000, 16000).backend == "python"  # identity needs neither


def test_numpy_path_validates_length():
    with pytest.raises(ValueError):
        Resampler(48000, 16000, use_numpy=True).process(b"\x00")
