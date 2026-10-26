"""G.711 mu-law codec and a small streaming polyphase resampler (pure Python).

Python 3.13 removed ``audioop``, so both are implemented here with lookup tables
and ``array``. PCM is signed 16-bit little-endian mono throughout. Sized for
8 kHz telephone audio: 20 ms of call audio costs well under a millisecond.
"""

from array import array
from functools import lru_cache
from math import ceil, cos, gcd, pi, sin, sqrt
from operator import mul
import sys

MULAW_BIAS = 0x84
MULAW_CLIP = 32635
PHONE_RATE = 8000
_BIG_ENDIAN = sys.byteorder == "big"


def _decode_sample(code):
    code = ~code & 0xFF
    exponent = (code >> 4) & 0x07
    magnitude = ((((code & 0x0F) << 3) + MULAW_BIAS) << exponent) - MULAW_BIAS
    return -magnitude if code & 0x80 else magnitude


def _encode_sample(sample):
    sign = 0x80 if sample < 0 else 0x00
    magnitude = min(-sample if sample < 0 else sample, MULAW_CLIP) + MULAW_BIAS
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not magnitude & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (magnitude >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


# 256 decoded samples, indexed by the mu-law byte.
DECODE_TABLE = array("h", (_decode_sample(code) for code in range(256)))


@lru_cache(maxsize=1)
def _encode_table():
    """65536 mu-law bytes indexed by the sample's unsigned 16-bit pattern (built once)."""
    return bytes(_encode_sample(value - 65536 if value >= 32768 else value) for value in range(65536))


def _pcm_array(pcm, typecode="h"):
    if len(pcm) % 2:
        raise ValueError("PCM16 data must have an even number of bytes.")
    samples = array(typecode)
    samples.frombytes(pcm)
    if _BIG_ENDIAN:
        samples.byteswap()
    return samples


def _pcm_bytes(samples):
    if _BIG_ENDIAN:
        samples = array("h", samples)
        samples.byteswap()
    return samples.tobytes()


def mulaw_decode(data):
    """mu-law bytes -> PCM16 little-endian bytes (one sample per input byte)."""
    return _pcm_bytes(array("h", map(DECODE_TABLE.__getitem__, data)))


def mulaw_encode(pcm):
    """PCM16 little-endian bytes -> mu-law bytes."""
    return bytes(map(_encode_table().__getitem__, _pcm_array(pcm, "H")))


def _bessel_i0(value):
    total = term = 1.0
    k = 1
    while term > 1e-12 * total:
        term *= (value / (2.0 * k)) ** 2
        total += term
        k += 1
    return total


@lru_cache(maxsize=16)
def _design(source_rate, target_rate):
    """Kaiser-windowed sinc prototype split into reversed polyphase branches.

    The transition band is centred on the lower rate's Nyquist frequency (4 kHz
    for every telephone conversion), +-15 %, with about 60 dB stopband.
    """
    divisor = gcd(source_rate, target_rate)
    up, down = target_rate // divisor, source_rate // divisor
    rate = source_rate * up
    cutoff = min(source_rate, target_rate) / 2.0
    transition = 0.3 * cutoff
    attenuation = 60.0
    beta = 0.1102 * (attenuation - 8.7)
    length = int(ceil((attenuation - 8.0) / (2.285 * 2 * pi * transition / rate))) + 1
    length = int(ceil(length / up)) * up
    centre = (length - 1) / 2.0
    normalized = cutoff / rate
    i0_beta = _bessel_i0(beta)
    taps = []
    for k in range(length):
        x = k - centre
        ideal = 2 * normalized if x == 0 else sin(2 * pi * normalized * x) / (pi * x)
        ratio = 2.0 * k / (length - 1) - 1.0
        window = _bessel_i0(beta * sqrt(max(0.0, 1.0 - ratio * ratio))) / i0_beta
        taps.append(ideal * window)
    scale = up / sum(taps)
    taps = [value * scale for value in taps]
    per_phase = length // up
    phases = tuple(
        tuple(taps[phase + j * up] for j in range(per_phase - 1, -1, -1)) for phase in range(up)
    )
    return up, down, per_phase, phases


class Resampler:
    """Streaming rational resampler for PCM16; keeps filter history between chunks."""

    def __init__(self, source_rate, target_rate):
        if source_rate <= 0 or target_rate <= 0:
            raise ValueError("Sample rates must be positive.")
        self.source_rate, self.target_rate = source_rate, target_rate
        self.identity = source_rate == target_rate
        if not self.identity:
            self.up, self.down, self.width, self.phases = _design(source_rate, target_rate)
            self.reset()

    def reset(self):
        if not self.identity:
            self.history = [0] * (self.width - 1)
            self.position = 0

    def process(self, pcm):
        if self.identity:
            _pcm_array(pcm)  # validates the length
            return bytes(pcm)
        samples = _pcm_array(pcm)
        buffer = self.history + samples.tolist()
        up, down, width, phases = self.up, self.down, self.width, self.phases
        limit = len(samples) * up
        position = self.position
        output = []
        append = output.append
        while position < limit:
            base, phase = divmod(position, up)
            value = round(sum(map(mul, phases[phase], buffer[base : base + width])))
            append(32767 if value > 32767 else -32768 if value < -32768 else value)
            position += down
        self.position = position - limit
        self.history = buffer[len(buffer) - (width - 1) :] if width > 1 else []
        return _pcm_bytes(array("h", output))


def tone(frequency, seconds, rate=PHONE_RATE, amplitude=0.2):
    """Synthesized sine (no recording) with 10 ms fades, as PCM16 bytes."""
    count = int(rate * seconds)
    fade = max(1, int(rate * 0.01))
    peak = amplitude * 32767
    values = []
    for n in range(count):
        envelope = min(1.0, n / fade, (count - 1 - n) / fade)
        values.append(int(round(peak * envelope * sin(2 * pi * frequency * n / rate))))
    return _pcm_bytes(array("h", values))


def goertzel_power(pcm, frequency, rate):
    """Relative signal power at ``frequency`` (test and diagnostics helper)."""
    samples = _pcm_array(pcm)
    coefficient = 2 * cos(2 * pi * frequency / rate)
    previous = before = 0.0
    for sample in samples:
        previous, before = sample + coefficient * previous - before, previous
    return (previous * previous + before * before - coefficient * previous * before) / max(
        1, len(samples)
    ) ** 2
