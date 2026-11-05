"""Telephony gateway (C1): signatures, tokens, TwiML, Media Streams, audio, outbound
policy, tunnel supervisor, settings and secrets. No network and no real Twilio."""

from array import array
import asyncio
import base64
from contextlib import contextmanager
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from services.settings import CALLS_DEFAULTS, SettingsPatch, SettingsService, SettingsStore
from services.tools import ServiceError
from telephony import twiml
from telephony.audio import (
    DECODE_TABLE,
    Resampler,
    goertzel_power,
    mulaw_decode,
    mulaw_encode,
    tone,
)
from telephony.grants import CallGrant, in_quiet_hours, purpose_hash
from telephony.media import CallAudioSession, MediaStreamHandler, StreamClosed
from telephony.numbers import mask, normalize, withheld
from telephony.service import (
    EVENT_OWNER_UNREACHABLE,
    EVENT_VOICEMAIL,
    TelephonyService,
    calls_settings,
)
from telephony.signature import compute_signature, url_variants, valid_signature
from telephony.stub_agent import stub_agent
from telephony.tokens import OutboundTickets, Signer, StreamTokens, TokenError
from telephony.tunnel import ARGUMENTS, TunnelSupervisor, locate_cloudflared

ACCOUNT = "AC" + "0123456789abcdef" * 2
TOKEN = "0123456789abcdef" * 2
JARVIS = "+60312345678"
OWNER = "+60123456789"
FRIEND = "+60198765432"
BASE = "https://calls.example.com"
CALL = "CA" + "a" * 32
STREAM = "MZ" + "b" * 32
TUNNEL = "eyJhIjoi" + "A1b2C3d4" * 20
KL = ZoneInfo("Asia/Kuala_Lumpur")


def kl_time(hour, minute=0):
    return datetime(2026, 10, 26, hour, minute, tzinfo=KL).timestamp()


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class FakeSecrets:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, name):
        return self.values.get(name)

    def status(self, name):
        configured = name in self.values
        return {"configured": configured, "verified_at": None, "source": "store" if configured else None}


class FakeDatabase:
    def __init__(self):
        self.documents = {}

    @contextmanager
    def connection(self):
        yield self

    transaction = connection

    def get(self, db, kind, key):
        return copy.deepcopy(self.documents.get((kind, key)))

    def put(self, db, kind, key, value):
        self.documents[(kind, key)] = copy.deepcopy(value)


class FakeBus:
    def __init__(self):
        self.events = []

    def emit_nowait(self, event):
        self.events.append(event)


class FakeApp:
    def __init__(self, calls=None, secrets=None):
        self.settings = {"calls": {**CALLS_DEFAULTS, "enabled": True, "public_base_url": BASE,
                                   **(calls or {})}}
        self.secrets = FakeSecrets(
            secrets if secrets is not None else {
                "twilio_account_sid": ACCOUNT,
                "twilio_auth_token": TOKEN,
                "twilio_phone_number": JARVIS,
                "owner_phone_number": OWNER,
            }
        )
        self.database = FakeDatabase()
        self.bus = FakeBus()


class Tunnel:
    def status(self):
        return {"state": "stopped", "binary_found": False, "exit_code": None, "restarts": 0}

    async def start(self):
        return self.status()

    async def stop(self):
        return self.status()


async def idle_agent(session):
    async for _frame in session:
        pass


def make_service(calls=None, secrets=None, clock=None, transport=None, agent=idle_agent):
    app = FakeApp(calls, secrets)
    service = TelephonyService(
        app, port=0, clock=clock or time.time, transport=transport, tunnel=Tunnel(), environ={}
    )
    if agent is not None:
        service.set_agent(agent)
    return service


def xml(document):
    root = ElementTree.fromstring(document)
    assert root.tag == "Response"
    return root


def inbound_params(**overrides):
    return {
        "AccountSid": ACCOUNT, "CallSid": CALL, "From": "+60111111111", "To": JARVIS,
        "Direction": "inbound", "CallStatus": "ringing", **overrides,
    }


# --- signatures ------------------------------------------------------------------------

TWILIO_URL = "https://mycompany.com/myapp.php?foo=1&bar=2"


@pytest.mark.parametrize(
    "caller,expected",
    [
        # Twilio's documented example (docs "Validating requests", Auth Token 12345).
        ("+12349013030", "0/KCTR6DLpKmkAf8muzZqo1nDgQ="),
        # The vector in Twilio's helper-library tests (twilio-python RequestValidator).
        ("+14158675309", "RSOYDt4T1cUTdK1PDd93/VVr8B8="),
    ],
)
def test_twilio_published_signature_vectors(caller, expected):
    params = {"CallSid": "CA1234567890ABCDE", "Caller": caller, "Digits": "1234",
              "From": caller, "To": "+18005551212"}
    assert compute_signature("12345", TWILIO_URL, params) == expected
    assert valid_signature("12345", [TWILIO_URL], params, expected)
    reordered = list(reversed(list(params.items())))
    assert compute_signature("12345", TWILIO_URL, reordered) == expected


def test_signature_rejects_tampering_missing_and_url_mismatch():
    params = [("CallSid", CALL), ("From", "+60111111111"), ("To", JARVIS)]
    url = BASE + "/telephony/voice/inbound"
    good = compute_signature(TOKEN, url, params)
    assert valid_signature(TOKEN, [url], params, good)
    assert not valid_signature(TOKEN, [url], params, "")
    assert not valid_signature(TOKEN, [url], params, None)
    assert not valid_signature(TOKEN, [url], params, "x" * 500)
    assert not valid_signature(TOKEN, [url], [*params[:-1], ("To", FRIEND)], good)
    assert not valid_signature(TOKEN, [url], [*params, ("Extra", "1")], good)
    assert not valid_signature(TOKEN, [url + "?a=1"], params, good)
    assert not valid_signature(TOKEN, ["http://127.0.0.1:8790/telephony/voice/inbound"], params, good)
    assert not valid_signature("f" * 32, [url], params, good)
    assert not valid_signature(None, [url], params, good)


def test_signature_accepts_default_port_spellings_only():
    params = {"CallSid": CALL}
    with_port = compute_signature(TOKEN, "https://calls.example.com:443/telephony/status", params)
    assert valid_signature(TOKEN, [BASE + "/telephony/status"], params, with_port)
    other = compute_signature(TOKEN, "https://calls.example.com:8443/telephony/status", params)
    assert not valid_signature(TOKEN, [BASE + "/telephony/status"], params, other)
    assert url_variants("wss://h.example/x") == ["wss://h.example/x", "wss://h.example:443/x"]


def test_repeated_parameters_sign_each_value_sorted():
    params = [("B", "2"), ("A", "z"), ("A", "y")]
    assert compute_signature(TOKEN, "https://x.example/p", params) == compute_signature(
        TOKEN, "https://x.example/p", [("A", "y"), ("A", "z"), ("B", "2")]
    )


# --- stream tokens and tickets -------------------------------------------------------


def test_stream_token_is_bound_single_use_and_expires():
    clock = Clock(1000.0)
    tokens = StreamTokens(Signer(clock=clock))
    token = tokens.issue(CALL, "inbound")
    with pytest.raises(TokenError) as error:
        tokens.redeem(token, "CA" + "c" * 32, "inbound")
    assert error.value.code == "token_mismatch"
    with pytest.raises(TokenError) as error:
        tokens.redeem(token, CALL, "outbound")
    assert error.value.code == "token_mismatch"
    tokens.redeem(token, CALL, "inbound")
    with pytest.raises(TokenError) as error:
        tokens.redeem(token, CALL, "inbound")
    assert error.value.code == "token_replayed"
    late = tokens.issue(CALL, "inbound")
    clock.value += 121
    with pytest.raises(TokenError) as error:
        tokens.redeem(late, CALL, "inbound")
    assert error.value.code == "token_expired"


@pytest.mark.parametrize("mutate", ["payload", "signature", "empty", "garbage", "huge"])
def test_tampered_stream_tokens_are_invalid(mutate):
    tokens = StreamTokens(Signer())
    token = tokens.issue(CALL, "inbound")
    payload, _, signature = token.partition(".")
    forged = {
        "payload": base64.urlsafe_b64encode(b'{"p":"jarvis-media-stream-v1","c":"' + CALL.encode()
                                            + b'","d":"inbound","n":"x","x":99999999999}').decode().rstrip("=")
        + "." + signature,
        "signature": payload + "." + signature[:-2] + ("AA" if signature[-2:] != "AA" else "BB"),
        "empty": "",
        "garbage": "not-a-token",
        "huge": "a" * 5000,
    }[mutate]
    with pytest.raises(TokenError):
        tokens.redeem(forged, CALL, "inbound")


def test_tokens_do_not_cross_purposes_or_restarts():
    signer = Signer()
    ticket = OutboundTickets(signer).issue("call-1")
    with pytest.raises(TokenError):
        StreamTokens(signer).redeem(ticket, CALL, "inbound")
    stream = StreamTokens(signer).issue(CALL, "inbound")
    with pytest.raises(TokenError):
        OutboundTickets(signer).redeem(stream)
    with pytest.raises(TokenError) as error:
        StreamTokens(Signer()).redeem(stream, CALL, "inbound")  # a restarted core
    assert error.value.code == "token_invalid"


# --- TwiML -----------------------------------------------------------------------------


def test_inbound_twiml_connects_a_bidirectional_stream_with_token():
    service = make_service()
    root = xml(service.inbound_twiml(inbound_params()))
    stream = root.find("Connect/Stream")
    assert stream.get("url") == "wss://calls.example.com/telephony/media"
    parameters = {item.get("name"): item.get("value") for item in stream.findall("Parameter")}
    assert set(parameters) == {"token", "direction"} and parameters["direction"] == "inbound"
    service.stream_tokens.redeem(parameters["token"], CALL, "inbound")
    assert [child.tag for child in root] == ["Connect"]
    assert service.inbound[CALL]["from"] == "+60111111111"


def test_twiml_escapes_values():
    document = twiml.connect_stream('wss://h.example/m?"<x>&', {"t": 'a"b<c>&d'})
    stream = xml(document).find("Connect/Stream")
    assert stream.get("url") == 'wss://h.example/m?"<x>&'
    assert stream.find("Parameter").get("value") == 'a"b<c>&d'
    assert b"<x>" not in document and b'a"b' not in document
    assert xml(twiml.say_and_hangup("<Hangup/> & more")).find("Say").text == "<Hangup/> & more"


@pytest.mark.parametrize("mode", ["voicemail", "hangup"])
def test_kill_switch_routes_to_voicemail_or_hangup(mode):
    service = make_service({"enabled": False, "when_disabled": mode})
    root = xml(service.inbound_twiml(inbound_params()))
    tags = [child.tag for child in root]
    assert root.find("Connect") is None
    assert tags == (["Say", "Record", "Hangup"] if mode == "voicemail" else ["Say", "Hangup"])
    assert not service.inbound


def test_voicemail_result_is_thanked_not_recorded_again():
    service = make_service({"enabled": False})
    root = xml(service.inbound_twiml(inbound_params(RecordingSid="RE" + "1" * 32,
                                                    RecordingDuration="7")))
    assert [child.tag for child in root] == ["Say", "Hangup"]
    assert [event.type for event in service.app.bus.events] == [EVENT_VOICEMAIL]


def test_no_agent_or_missing_number_takes_the_unavailable_path():
    service = make_service(agent=None)
    assert xml(service.inbound_twiml(inbound_params())).find("Connect") is None
    unconfigured = make_service(secrets={"twilio_account_sid": ACCOUNT, "twilio_auth_token": TOKEN})
    assert xml(unconfigured.inbound_twiml(inbound_params())).find("Connect") is None


@pytest.mark.parametrize("enabled", [True, False])
def test_loop_guard_rejects_jarviss_own_number_first(enabled):
    service = make_service({"enabled": enabled})
    service.register_outbound("owner-call", OWNER, "briefing", None, True)
    service.outbound_placed("owner-call", "CA" + "d" * 32, "ringing")
    root = xml(service.inbound_twiml(inbound_params(From=JARVIS)))
    assert [child.tag for child in root] == ["Reject"]
    (event,) = service.app.bus.events
    assert event.type == EVENT_OWNER_UNREACHABLE
    assert event.data == {"reason": "forwarded_back", "inbound_call_sid": CALL,
                          "outbound_call_sid": "CA" + "d" * 32, "call_id": "owner-call"}


def test_loop_guard_withheld_caller_forwarded_from_owner():
    service = make_service()
    withheld_forward = inbound_params(From="+266696687", ForwardedFrom=OWNER)
    # No sign that JARVIS is the caller: a withheld caller forwarded by the owner is screened.
    assert xml(service.inbound_twiml(withheld_forward)).find("Connect") is not None
    by_name = inbound_params(From="Anonymous", ForwardedFrom=OWNER, CallerName=JARVIS)
    assert [c.tag for c in xml(service.inbound_twiml(by_name))] == ["Reject"]
    service.register_outbound("owner-call", OWNER, "briefing", None, True)
    assert [c.tag for c in xml(service.inbound_twiml(withheld_forward))] == ["Reject"]
    assert [e.data["reason"] for e in service.app.bus.events] == ["forwarded_withheld"] * 2
    # A visible third-party caller forwarded while JARVIS rings the owner is not rejected.
    visible = inbound_params(From=FRIEND, ForwardedFrom=OWNER)
    assert xml(service.inbound_twiml(visible)).find("Connect") is not None


def test_number_helpers():
    assert normalize(" +60 12-345 6789 ") == "+60123456789"
    assert normalize("0123456789") is None and normalize(None) is None
    assert all(withheld(value) for value in ("", "anonymous", "+266696687", "+7378742833", None))
    assert not withheld(FRIEND)
    assert mask(FRIEND) == "***5432" and mask("anonymous") == "withheld"


# --- audio -----------------------------------------------------------------------------


def test_mulaw_decode_matches_the_g711_reference_table():
    # ITU-T G.711 mu-law expansion at 16-bit scale (as audioop.ulaw2lin).
    assert list(DECODE_TABLE[:8]) == [-32124, -31100, -30076, -29052, -28028, -27004, -25980, -24956]
    assert list(DECODE_TABLE[0x70:0x80]) == [-120, -112, -104, -96, -88, -80, -72, -64,
                                             -56, -48, -40, -32, -24, -16, -8, 0]
    assert (DECODE_TABLE[0x10], DECODE_TABLE[0x20], DECODE_TABLE[0x80], DECODE_TABLE[0xFF]) == (
        -15996, -7932, 32124, 0)
    assert mulaw_decode(bytes([0x80, 0x00])) == (32124).to_bytes(2, "little", signed=True) + (
        -32124).to_bytes(2, "little", signed=True)


def test_mulaw_encode_reference_values_and_round_trip():
    pcm = b"".join(v.to_bytes(2, "little", signed=True) for v in (0, 1, -1, 32767, -32768, 8, -8))
    assert mulaw_encode(pcm) == bytes([0xFF, 0xFF, 0x7F, 0x80, 0x00, 0xFE, 0x7E])
    codes = bytes(range(256))
    round_trip = mulaw_encode(mulaw_decode(codes))
    assert [c for c in range(256) if round_trip[c] != c] == [0x7F]  # -0 encodes as +0
    for value in range(-32768, 32768, 37):
        decoded = int.from_bytes(mulaw_decode(mulaw_encode(value.to_bytes(2, "little", signed=True))),
                                 "little", signed=True)
        # Half a quantization step: 4 << segment, i.e. (|x| + bias) / 32; beyond the clip
        # level (32635) the largest code decodes to 32124.
        bound = (abs(value) + 132) / 32 + 0.5 if abs(value) <= 32635 else 645
        assert abs(decoded - value) <= bound
    with pytest.raises(ValueError):
        mulaw_encode(b"\x00")


@pytest.mark.parametrize(
    "source,target,chunk",
    [(8000, 16000, 160), (16000, 8000, 320), (24000, 8000, 480), (24000, 16000, 480)],
)
def test_resampler_preserves_frequency_and_length(source, target, chunk):
    signal = tone(1000, 1.0, source, 0.5)
    resampler = Resampler(source, target)
    output = b"".join(resampler.process(signal[i : i + chunk * 2])
                      for i in range(0, len(signal), chunk * 2))
    assert len(output) // 2 == len(signal) // 2 * target // source
    steady = output[len(output) // 4 :]
    wanted = goertzel_power(steady, 1000, target)
    for other in (500, 1500, 2500, 3500):
        assert wanted > 1000 * goertzel_power(steady, other, target)  # > 30 dB
    # Chunked streaming equals one pass: the filter state carries across chunks.
    assert output == Resampler(source, target).process(signal)


def test_resampler_rejects_aliases_and_keeps_dc():
    reference = Resampler(24000, 8000).process(tone(1000, 0.5, 24000, 0.5))
    aliased = Resampler(24000, 8000).process(tone(6000, 0.5, 24000, 0.5))  # would fold to 2 kHz
    assert goertzel_power(aliased[1600:], 2000, 8000) * 1e5 < goertzel_power(reference[1600:], 1000, 8000)
    constant = (1000).to_bytes(2, "little", signed=True) * 4000
    for source, target in ((8000, 16000), (24000, 8000)):
        out = array("h", Resampler(source, target).process(constant))
        assert all(abs(sample - 1000) <= 3 for sample in out[len(out) // 2 :])


def test_tone_is_synthesized_pcm():
    pcm = tone(440, 0.4)
    assert len(pcm) == 2 * 3200
    assert goertzel_power(pcm, 440, 8000) > 100 * goertzel_power(pcm, 1000, 8000)


# --- Media Streams ---------------------------------------------------------------------

CLOSED = object()


class FakeSocket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = None

    def push(self, message):
        self.incoming.put_nowait(message if isinstance(message, str) else json.dumps(message))

    async def receive_text(self):
        item = await self.incoming.get()
        if item is CLOSED:
            raise WebSocketDisconnect(1000)
        return item

    async def send_text(self, text):
        if self.closed is not None:
            raise RuntimeError("closed")
        self.sent.append(json.loads(text))

    async def close(self, code=1000):
        if self.closed is None:
            self.closed = code
            self.incoming.put_nowait(CLOSED)


def start_message(token, direction="inbound", **media):
    return {
        "event": "start", "sequenceNumber": "1", "streamSid": STREAM,
        "start": {
            "accountSid": ACCOUNT, "streamSid": STREAM, "callSid": CALL, "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1, **media},
            "customParameters": {"token": token, "direction": direction},
        },
    }


def media_message(data, sequence=2):
    return {"event": "media", "sequenceNumber": str(sequence), "streamSid": STREAM,
            "media": {"track": "inbound", "chunk": "1", "timestamp": "20",
                      "payload": base64.b64encode(data).decode()}}


def handler_for(service, socket, **options):
    return MediaStreamHandler(socket, service.authorize_stream, on_open=service.session_opened,
                              on_close=service.session_closed, **options)


async def test_media_stream_protocol_round_trip():
    state, ready, cleared = {}, asyncio.Event(), asyncio.Event()

    async def agent(session):
        state["info"] = session.info
        state["frame"] = await session.read(timeout=2)
        await session.send(tone(1000, 0.1, 24000), 24000)
        first = await session.mark("greeting")
        ready.set()
        state["played"] = await asyncio.wait_for(first, 2)
        second = await session.mark()
        await session.send(tone(500, 0.04, 16000), 16000)
        assert session.playing
        await session.clear()
        state["cleared"] = await second
        assert not session.playing
        cleared.set()
        state["digit"] = await asyncio.wait_for(session.digits.get(), 2)
        async for _frame in session:
            pass
        state["ended"] = session.end_reason

    service = make_service(agent=agent)
    service.inbound_twiml(inbound_params())  # records caller details for the session
    token = service.stream_tokens.issue(CALL, "inbound")
    socket = FakeSocket()
    task = asyncio.create_task(handler_for(service, socket).run())
    socket.push({"event": "connected", "protocol": "Call", "version": "1.0.0"})
    socket.push(start_message(token))
    socket.push(media_message(b"\xff" * 160))
    await asyncio.wait_for(ready.wait(), 2)
    assert service.sessions[CALL].stream_sid == STREAM
    media = [m for m in socket.sent if m["event"] == "media"]
    assert len(media) == 5 and all(m["streamSid"] == STREAM for m in media)
    assert sum(len(base64.b64decode(m["media"]["payload"])) for m in media) == 800
    assert socket.sent[-1] == {"event": "mark", "streamSid": STREAM, "mark": {"name": "greeting"}}
    socket.push({"event": "mark", "sequenceNumber": "3", "streamSid": STREAM,
                 "mark": {"name": "greeting"}})
    await asyncio.wait_for(cleared.wait(), 2)
    assert {"event": "clear", "streamSid": STREAM} in socket.sent
    socket.push({"event": "dtmf", "streamSid": STREAM, "sequenceNumber": "4",
                 "dtmf": {"track": "inbound_track", "digit": "5"}})
    socket.push({"event": "stop", "sequenceNumber": "5", "streamSid": STREAM,
                 "stop": {"accountSid": ACCOUNT, "callSid": CALL}})
    assert await asyncio.wait_for(task, 3) == "stopped"
    assert len(state["frame"]) == 640  # 20 ms at 16 kHz PCM16
    assert state["played"] is True and state["cleared"] is False
    assert state["digit"] == "5" and state["ended"] == "stopped"
    assert state["info"]["from"] == "+60111111111" and "received" not in state["info"]
    assert socket.closed == 1000 and not service.sessions and CALL not in service.inbound


@pytest.mark.parametrize(
    "first,reason",
    [
        ("bad_token", "token_invalid"),
        ("wrong_direction", "token_mismatch"),
        ("media_first", "expected_start"),
        ("wrong_format", "unsupported_media_format"),
        ("bad_json", "malformed_message"),
        ("wrong_account", "wrong_account"),
    ],
)
async def test_media_stream_refuses_bad_starts(first, reason):
    started = []

    async def agent(session):
        started.append(session)

    service = make_service(agent=agent)
    token = service.stream_tokens.issue(CALL, "inbound")
    socket = FakeSocket()
    message = {
        "bad_token": start_message("forged." + token.partition(".")[2]),
        "wrong_direction": start_message(token, direction="outbound"),
        "media_first": media_message(b"\xff" * 160),
        "wrong_format": start_message(token, sampleRate=16000),
        "bad_json": "{not json",
        "wrong_account": {**start_message(token), "start": {**start_message(token)["start"],
                                                            "accountSid": "AC" + "9" * 32}},
    }[first]
    socket.push(message)
    assert await asyncio.wait_for(handler_for(service, socket).run(), 2) == reason
    assert socket.closed == 1008 and not started and not service.sessions


async def test_media_stream_token_cannot_be_replayed():
    service = make_service()
    token = service.stream_tokens.issue(CALL, "inbound")
    first, second = FakeSocket(), FakeSocket()
    task = asyncio.create_task(handler_for(service, first).run())
    first.push(start_message(token))
    await asyncio.sleep(0.05)
    second.push(start_message(token))
    assert await asyncio.wait_for(handler_for(service, second).run(), 2) == "token_replayed"
    first.push({"event": "stop", "streamSid": STREAM})
    assert await asyncio.wait_for(task, 3) == "stopped"


async def test_media_stream_start_timeout_and_disconnect_teardown():
    service = make_service()
    socket = FakeSocket()
    assert await handler_for(service, socket, start_timeout=0.05).run() == "start_timeout"
    state = {}

    async def agent(session):
        mark = await session.mark("pending")
        frames = [frame async for frame in session]
        state.update(frames=frames, mark=mark.result(), reason=session.end_reason)
        with pytest.raises(StreamClosed):
            await session.send(b"\x00\x00" * 80, 8000)

    service.set_agent(agent)
    socket = FakeSocket()
    task = asyncio.create_task(handler_for(service, socket).run())
    socket.push(start_message(service.stream_tokens.issue(CALL, "inbound")))
    socket.push(media_message(b"\xff" * 160))
    await asyncio.sleep(0.05)
    socket.incoming.put_nowait(CLOSED)  # Twilio drops the connection
    assert await asyncio.wait_for(task, 3) == "disconnected"
    assert state["reason"] == "disconnected" and state["mark"] is False
    assert len(state["frames"]) == 1 and not service.sessions


async def test_agent_hangup_closes_the_stream_and_stub_agent_holds_briefly():
    service = make_service(agent=lambda session: stub_agent(session, hold_seconds=0.2))
    socket = FakeSocket()
    started = time.monotonic()
    task = asyncio.create_task(handler_for(service, socket).run())
    socket.push(start_message(service.stream_tokens.issue(CALL, "inbound")))
    assert await asyncio.wait_for(task, 3) == "agent_hangup"
    assert time.monotonic() - started < 2
    assert socket.closed == 1000
    events = [m["event"] for m in socket.sent]
    assert events.count("media") == 20 and events[-1] == "mark"  # 0.4 s tone in 20 ms chunks


async def test_failed_agent_ends_the_call():
    async def agent(session):
        raise RuntimeError("boom")

    service = make_service(agent=agent)
    socket = FakeSocket()
    task = asyncio.create_task(handler_for(service, socket).run())
    socket.push(start_message(service.stream_tokens.issue(CALL, "inbound")))
    assert await asyncio.wait_for(task, 3) == "agent_failed"
    assert socket.closed == 1008


def test_call_audio_session_validates_rates():
    async def noop(*_):
        return None

    with pytest.raises(ValueError):
        CallAudioSession(noop, noop, call_sid=CALL, stream_sid=STREAM, direction="inbound",
                         input_rate=44100)

    async def run():
        session = CallAudioSession(noop, noop, call_sid=CALL, stream_sid=STREAM,
                                   direction="inbound")
        with pytest.raises(ValueError):
            await session.send(b"\x00\x00", 44100)

    asyncio.run(run())


def test_stub_agent_is_never_the_default():
    service = TelephonyService(FakeApp(), port=0, tunnel=Tunnel(), environ={})
    assert service.agent is None and service.status()["agent"] == "none"
    developer = TelephonyService(FakeApp(), port=0, tunnel=Tunnel(),
                                 environ={"JARVIS_TELEPHONY_STUB_AGENT": "1"})
    assert developer.agent is stub_agent and developer.status()["agent"] == "stub"


# --- outbound calls ------------------------------------------------------------------


class Twilio:
    def __init__(self, status=201, body=None, error=None):
        self.requests = []
        self.status, self.body, self.error = status, body, error

    def __call__(self, request):
        request.read()
        self.requests.append(request)
        if self.error:
            raise self.error
        body = self.body if self.body is not None else {"sid": "CA" + "e" * 32, "status": "queued"}
        return httpx.Response(self.status, json=body)


def outbound_service(clock=None, calls=None, twilio=None):
    twilio = twilio or Twilio()
    service = make_service(calls, clock=clock or Clock(kl_time(12)),
                           transport=httpx.MockTransport(twilio))
    return service, twilio


def form(request):
    return parse_qs(request.content.decode(), keep_blank_values=True)


async def test_owner_call_needs_no_grant_and_has_the_right_shape():
    service, twilio = outbound_service(clock=Clock(kl_time(23)))  # quiet hours do not apply
    result = await service.place_call(OWNER, "Briefing about a missed call", {"caller": "x"})
    assert result["owner"] is True and result["call_sid"] == "CA" + "e" * 32
    (request,) = twilio.requests
    assert request.method == "POST"
    assert str(request.url) == f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}/Calls.json"
    assert request.headers["authorization"] == "Basic " + base64.b64encode(
        f"{ACCOUNT}:{TOKEN}".encode()).decode()
    fields = form(request)
    assert fields["To"] == [OWNER] and fields["From"] == [JARVIS]
    assert fields["Timeout"] == ["15"] and fields["Method"] == ["POST"]
    assert fields["StatusCallback"] == [BASE + "/telephony/status"]
    assert fields["StatusCallbackEvent"] == ["initiated", "ringing", "answered", "completed"]
    url = urlsplit(fields["Url"][0])
    assert f"{url.scheme}://{url.netloc}{url.path}" == BASE + "/telephony/voice/outbound"
    assert set(parse_qs(url.query)) == {"ticket"}
    assert "CallerId" not in fields and TOKEN not in request.content.decode()
    assert service.limits.today_count() == 0  # owner calls do not use the third-party cap


async def test_third_party_calls_require_a_one_use_grant():
    service, twilio = outbound_service()
    purpose = "Book a table for two at 8 pm"
    for grant, code in (
        (None, "call_grant_required"),
        ("made-up", "call_grant_invalid"),
        (CallGrant("forged", FRIEND, purpose_hash(purpose), time.time() + 60), "call_grant_invalid"),
    ):
        with pytest.raises(ServiceError) as error:
            await service.place_call(FRIEND, purpose, grant=grant)
        assert error.value.code == code
    other = service.grants.issue("+60177777777", purpose)
    with pytest.raises(ServiceError) as error:
        await service.place_call(FRIEND, purpose, grant=other)
    assert error.value.code == "call_grant_mismatch"
    grant = service.grants.issue(FRIEND, purpose)
    with pytest.raises(ServiceError) as error:
        await service.place_call(FRIEND, purpose + " and a cake", grant=grant)
    assert error.value.code == "call_grant_mismatch" and not grant.consumed
    assert twilio.requests == []
    result = await service.place_call(FRIEND, purpose, grant=grant)
    assert result["owner"] is False and grant.consumed
    with pytest.raises(ServiceError) as error:
        await service.place_call(FRIEND, purpose, grant=grant.id)
    assert error.value.code == "call_grant_used" and len(twilio.requests) == 1


async def test_grants_expire_within_ten_minutes():
    clock = Clock(kl_time(12))
    service, _ = outbound_service(clock=clock)
    grant = service.grants.issue(FRIEND, "Call", ttl=3600)
    assert grant.expires_at == clock.value + 600
    clock.value += 601
    with pytest.raises(ServiceError) as error:
        await service.place_call(FRIEND, "Call", grant=grant)
    assert error.value.code == "call_grant_expired"


@pytest.mark.parametrize("hour,minute,quiet", [(21, 0, True), (23, 59, True), (3, 0, True),
                                               (8, 59, True), (9, 0, False), (20, 59, False)])
def test_quiet_hours_wrap_midnight(hour, minute, quiet):
    from datetime import time as day

    assert in_quiet_hours(day(hour, minute), {"start": "21:00", "end": "09:00"}) is quiet
    assert in_quiet_hours(day(hour, minute), {"start": "09:00", "end": "09:00"}) is False


async def test_quiet_hours_refuse_third_parties_without_burning_the_grant():
    service, twilio = outbound_service(clock=Clock(kl_time(22, 30)))
    grant = service.grants.issue(FRIEND, "Call")
    with pytest.raises(ServiceError) as error:
        await service.place_call(FRIEND, "Call", grant=grant)
    assert error.value.code == "call_quiet_hours" and not grant.consumed and not twilio.requests
    await service.place_call(OWNER, "Briefing")
    assert len(twilio.requests) == 1


async def test_daily_cap_and_number_cooldown_persist():
    clock = Clock(kl_time(10))
    service, twilio = outbound_service(clock=clock, calls={"daily_outbound_cap": 2,
                                                           "number_cooldown_minutes": 30})
    await service.place_call(FRIEND, "One", grant=service.grants.issue(FRIEND, "One"))
    with pytest.raises(ServiceError) as error:
        await service.place_call(FRIEND, "Two", grant=service.grants.issue(FRIEND, "Two"))
    assert error.value.code == "call_number_cooldown"
    other = "+60177777777"
    await service.place_call(other, "Two", grant=service.grants.issue(other, "Two"))
    third = "+60166666666"
    with pytest.raises(ServiceError) as error:
        await service.place_call(third, "Three", grant=service.grants.issue(third, "Three"))
    assert error.value.code == "call_daily_cap" and len(twilio.requests) == 2
    restarted = TelephonyService(service.app, port=0, clock=clock, tunnel=Tunnel(), environ={})
    assert restarted.limits.today_count() == 2
    ledger = json.dumps(service.app.database.documents[("telephony", "outbound_ledger")])
    assert FRIEND not in ledger and other not in ledger  # numbers are stored as keyed hashes
    clock.value += 24 * 3600  # next day: the cap resets; the cooldown has passed
    await service.place_call(FRIEND, "Again", grant=service.grants.issue(FRIEND, "Again"))


async def test_outbound_refusals_before_any_request():
    service, twilio = outbound_service(calls={"enabled": False})
    with pytest.raises(ServiceError) as error:
        await service.place_call(OWNER, "Briefing")
    assert error.value.code == "calls_disabled"
    service, twilio = outbound_service()
    for number, code in ((JARVIS, "invalid_number"), ("0123", "invalid_number")):
        with pytest.raises(ServiceError) as error:
            await service.place_call(number, "Briefing")
        assert error.value.code == code
    service.app.secrets.values.pop("twilio_auth_token")
    with pytest.raises(ServiceError) as error:
        await service.place_call(OWNER, "Briefing")
    assert error.value.code == "calls_not_configured" and not twilio.requests


@pytest.mark.parametrize(
    "twilio,code",
    [
        (Twilio(status=401, body={"code": 20003}), "twilio_auth_failed"),
        (Twilio(status=400, body={"code": 21215, "message": "Geo permission for +60123456789"}),
         "twilio_rejected"),
        (Twilio(error=httpx.ConnectError("offline")), "twilio_unreachable"),
        (Twilio(body={"sid": "nope"}), "twilio_rejected"),
    ],
)
async def test_twilio_failures_are_reported_without_details(twilio, code):
    service, _ = outbound_service(twilio=twilio)
    with pytest.raises(ServiceError) as error:
        await service.place_call(OWNER, "Briefing")
    assert error.value.code == code and OWNER not in str(error.value)
    assert not service.outbound


async def test_outbound_twiml_uses_the_ticket_once_and_checks_the_call():
    service, twilio = outbound_service()
    result = await service.place_call(OWNER, "Briefing", {"why": "missed call"})
    ticket = parse_qs(urlsplit(form(twilio.requests[0])["Url"][0]).query)["ticket"][0]
    params = {"AccountSid": ACCOUNT, "CallSid": result["call_sid"], "From": JARVIS, "To": OWNER,
              "Direction": "outbound-api", "CallStatus": "in-progress"}
    with pytest.raises(ServiceError):
        service.outbound_twiml(ticket, {**params, "To": FRIEND})
    service2, twilio2 = outbound_service()
    await service2.place_call(OWNER, "Briefing")
    good = parse_qs(urlsplit(form(twilio2.requests[0])["Url"][0]).query)["ticket"][0]
    root = xml(service2.outbound_twiml(good, {**params, "CallSid": "CA" + "e" * 32}))
    stream = root.find("Connect/Stream")
    values = {p.get("name"): p.get("value") for p in stream.findall("Parameter")}
    assert values["direction"] == "outbound"
    info, _, _ = service2.authorize_stream({"account_sid": ACCOUNT, "call_sid": "CA" + "e" * 32,
                                            "token": values["token"], "direction": "outbound"})
    assert info["owner"] is True and info["purpose"] == "Briefing"
    with pytest.raises(ServiceError) as error:
        service2.outbound_twiml(good, {**params, "CallSid": "CA" + "e" * 32})
    assert error.value.code == "token_replayed"


async def test_status_callbacks_track_and_release_outbound_calls():
    service, _ = outbound_service()
    result = await service.place_call(OWNER, "Briefing")
    await service.status_callback({"CallSid": result["call_sid"], "CallStatus": "ringing"})
    assert service.outbound[result["call_id"]]["status"] == "ringing"
    await service.status_callback({"CallSid": result["call_sid"], "CallStatus": "no-answer"})
    assert not service.outbound and not service.outbound_by_sid
    await service.status_callback({"CallSid": "bogus", "CallStatus": "<x>"})
    assert [e.data["status"] for e in service.app.bus.events] == ["ringing", "no-answer"]


# --- tunnel supervisor ---------------------------------------------------------------


class FakeProcess:
    def __init__(self, executable, arguments, environment, cwd, exit_after=None):
        self.executable, self.arguments, self.environment = executable, arguments, environment
        self.running, self.code, self.terminated = True, None, False
        self.exit_after = exit_after
        self.polls = 0

    def alive(self):
        self.polls += 1
        if self.exit_after is not None and self.polls > self.exit_after:
            self.running, self.code = False, 3
        return self.running

    def exit_code(self):
        return self.code

    def terminate(self, timeout=5.0):
        self.running, self.terminated = False, True
        return True


async def test_tunnel_token_goes_in_the_environment_only(tmp_path):
    binary = tmp_path / "cloudflared.exe"
    binary.write_bytes(b"")
    spawned = []

    def factory(*args):
        spawned.append(FakeProcess(*args))
        return spawned[-1]

    tunnel = TunnelSupervisor(lambda: TUNNEL, locate=lambda: binary, process_factory=factory,
                              poll_seconds=0.01)
    status = await tunnel.start()
    await asyncio.sleep(0.05)
    assert tunnel.status()["state"] == "running" and status["binary_found"]
    (process,) = spawned
    assert process.arguments == [str(binary), *ARGUMENTS]
    assert all(TUNNEL not in str(item) for item in process.arguments)
    assert process.environment == {"TUNNEL_TOKEN": TUNNEL}
    assert (await tunnel.stop())["state"] == "stopped" and process.terminated


async def test_tunnel_reports_missing_token_binary_and_failures(tmp_path):
    assert (await TunnelSupervisor(lambda: None, locate=lambda: tmp_path).start())["state"] == (
        "not_configured")
    missing = await TunnelSupervisor(lambda: TUNNEL, locate=lambda: None).start()
    assert missing == {"state": "missing_binary", "binary_found": False, "exit_code": None,
                       "restarts": 0}
    tunnel = TunnelSupervisor(
        lambda: TUNNEL, locate=lambda: tmp_path / "cloudflared.exe",
        process_factory=lambda *args: FakeProcess(*args, exit_after=1),
        restart_delays=(0.01, 0.01), poll_seconds=0.01,
    )
    await tunnel.start()
    await asyncio.wait_for(tunnel.task, 2)
    assert tunnel.status() == {"state": "failed", "binary_found": True, "exit_code": 3,
                               "restarts": 2}
    await tunnel.stop()


def test_locate_cloudflared(tmp_path):
    binary = tmp_path / "cloudflared.exe"
    binary.write_bytes(b"")
    assert locate_cloudflared({"JARVIS_CLOUDFLARED": str(binary)}) == binary
    assert locate_cloudflared({"JARVIS_CLOUDFLARED": str(tmp_path / "nope.exe")}) is None
    assert locate_cloudflared({"PATH": str(tmp_path)}, which=lambda name, path: str(binary)) == binary
    empty = {"PATH": "", "ProgramFiles": str(tmp_path / "none")}
    assert locate_cloudflared(empty, which=lambda name, path: None) is None
    installed = tmp_path / "pf" / "cloudflared" / "cloudflared.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"")
    assert locate_cloudflared({"ProgramFiles": str(tmp_path / "pf")},
                              which=lambda name, path: None) == installed


FAKE_CLOUDFLARED = '''
import json, os, sys, time
record, mode = sys.argv[1], sys.argv[2]
with open(record, "w", encoding="utf-8") as stream:
    json.dump({"argv": sys.argv[3:], "token": os.environ.get("TUNNEL_TOKEN")}, stream)
if mode == "exit":
    sys.exit(7)
time.sleep(60)
'''


@pytest.mark.skipif(os.name != "nt", reason="owned job objects are Windows-only")
async def test_fake_cloudflared_runs_in_an_owned_job(tmp_path):
    script = tmp_path / "fake_cloudflared.py"
    script.write_text(FAKE_CLOUDFLARED, encoding="utf-8")
    record = tmp_path / "record.json"
    tunnel = TunnelSupervisor(
        lambda: TUNNEL, launcher=[sys.executable, "-I", str(script), str(record), "hold"],
        poll_seconds=0.05,
    )
    await tunnel.start()
    for _ in range(200):
        if record.exists() and record.stat().st_size:
            break
        await asyncio.sleep(0.05)
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert seen == {"argv": list(ARGUMENTS), "token": TUNNEL}
    assert tunnel.status()["state"] == "running"
    process = tunnel.process
    await tunnel.stop()
    assert tunnel.state == "stopped" and process.process is None and tunnel.process is None

    record.unlink()
    failing = TunnelSupervisor(
        lambda: TUNNEL, launcher=[sys.executable, "-I", str(script), str(record), "exit"],
        restart_delays=(), poll_seconds=0.05,
    )
    await failing.start()
    await asyncio.wait_for(failing.task, 30)
    assert failing.status()["state"] == "failed" and failing.status()["exit_code"] == 7
    await failing.stop()


# --- settings and secrets --------------------------------------------------------------


@pytest.mark.parametrize(
    "calls",
    [
        {"public_base_url": "http://calls.example.com"},
        {"public_base_url": "https://calls.example.com/"},
        {"public_base_url": "https://calls.example.com/telephony"},
        {"public_base_url": "https://user@calls.example.com"},
        {"public_base_url": "https://calls.example.com:8443"},
        {"public_base_url": "https://localhost"},
        {"quiet_hours": {"start": "9:00", "end": "21:00"}},
        {"quiet_hours": {"start": "21:00"}},
        {"daily_outbound_cap": -1},
        {"daily_outbound_cap": 101},
        {"daily_outbound_cap": "10"},
        {"number_cooldown_minutes": 10081},
        {"when_disabled": "forward"},
        {"enabled": "yes"},
        {"enabled": None},
        {"port": 8000},
        {},
    ],
)
def test_calls_settings_validation(calls):
    with pytest.raises(ValidationError):
        SettingsPatch.model_validate({"calls": calls})


def test_calls_settings_merge_with_defaults_and_stay_off_by_default():
    settings = {"tool_permissions": {}}
    service = SettingsService(settings, SettingsStore(None), ())
    assert calls_settings(settings) == CALLS_DEFAULTS and CALLS_DEFAULTS["enabled"] is False
    service.apply(SettingsPatch.model_validate({"calls": {"public_base_url": BASE}}))
    assert settings["calls"] == {**CALLS_DEFAULTS, "public_base_url": BASE}
    service.apply(SettingsPatch.model_validate({"calls": {"enabled": True, "quiet_hours": {
        "start": "22:00", "end": "08:00"}}}))
    assert settings["calls"]["enabled"] and settings["calls"]["public_base_url"] == BASE
    assert settings["calls"]["quiet_hours"] == {"start": "22:00", "end": "08:00"}
    broken = {"calls": {"enabled": "true", "public_base_url": "http://x", "daily_outbound_cap": 5000,
                        "quiet_hours": "never", "when_disabled": 1}}
    assert calls_settings(broken) == CALLS_DEFAULTS
    assert calls_settings({"calls": []}) == CALLS_DEFAULTS


def test_telephony_secret_formats():
    from services.secrets import spec_for

    cases = {
        "twilio_account_sid": (ACCOUNT, ["AC" + "0" * 31, "ac" + "0" * 32, "AC" + "G" * 32]),
        "twilio_auth_token": (TOKEN, ["0" * 31, "Z" * 32, TOKEN + " "]),
        "twilio_phone_number": (JARVIS, ["+12025550123", "60312345678", "+60 3 1234 5678"]),
        "owner_phone_number": (OWNER, ["0123456789", "+0123456789", "+60123"]),
        "cloudflare_tunnel_token": (TUNNEL, ["short", "cloudflared service install " + TUNNEL]),
    }
    for name, (good, bad) in cases.items():
        spec = spec_for(name)
        assert spec.valid(good), name
        assert not any(spec.valid(value) for value in bad), name


class Sender:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        return 200, "{}"


@pytest.mark.skipif(os.name != "nt", reason="DPAPI store requires Windows")
def test_twilio_checks_pair_sid_and_token(tmp_path):
    from services.secrets import SecretStore
    from services.storage import Database

    store = SecretStore(Database(tmp_path / "db"), environ={}, send=Sender())
    store.set("twilio_account_sid", ACCOUNT)
    assert store.test("twilio_account_sid")["last_check"]["code"] == "incomplete"
    assert store.send.calls == []
    store.set("twilio_auth_token", TOKEN)
    store.test("twilio_auth_token")
    store.test("twilio_account_sid")
    expected = (f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}.json",
                {"Authorization": "Basic " + base64.b64encode(f"{ACCOUNT}:{TOKEN}".encode()).decode()})
    assert store.send.calls == [expected, expected]
    store.set("owner_phone_number", OWNER)
    assert store.test("owner_phone_number")["last_check"]["code"] == "no_check"
    text = json.dumps(store.statuses())
    assert TOKEN not in text and ACCOUNT not in text and OWNER not in text
    statuses = {item["name"]: item for item in store.statuses()}
    assert statuses["twilio_auth_token"]["verified_at"] and statuses["twilio_auth_token"]["hint"] == TOKEN[-4:]


def test_secret_store_checks_are_unchanged_for_ai_keys():
    from services.secrets import REGISTRY

    assert REGISTRY["anthropic_api_key"].companions == () and REGISTRY["gemini_api_key"].companions == ()
    assert list(REGISTRY)[:2] == ["anthropic_api_key", "gemini_api_key"]


def test_status_reports_readiness_without_values():
    service = make_service(calls={"enabled": False})
    status = service.status()
    assert status["kill_switch"] is True and status["ready"] is False
    assert status["secrets"]["twilio_auth_token"] == {"configured": True, "verified": False,
                                                      "source": "store"}
    assert status["secrets"]["cloudflare_tunnel_token"]["configured"] is False
    assert TOKEN not in json.dumps(status) and ACCOUNT not in json.dumps(status)
    assert status["gateway"]["listening"] is False and status["gateway"]["host"] == "127.0.0.1"


def test_repository_docs_list_the_telephony_secrets():
    root = Path(__file__).resolve().parents[1]
    text = (root / "docs/AI_PROVIDERS.md").read_text(encoding="utf-8")
    from services.secrets import REGISTRY

    for name in ("twilio_account_sid", "twilio_auth_token", "twilio_phone_number",
                 "owner_phone_number", "cloudflare_tunnel_token"):
        assert name in REGISTRY and f"`{name}`" in text and REGISTRY[name].env in text
