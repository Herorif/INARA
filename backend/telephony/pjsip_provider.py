"""
PJSIP telephony provider for INARA.

Uses the pjsua2 Python bindings (part of PJSIP) for SIP communication.
Designed for homelab use with Asterisk, FreePBX, or any SIP PBX.

Threading model — CRITICAL:
  PJSIP runs its own C++ threads and fires Python callbacks (onIncomingCall,
  onCallState, onStreamCreated, etc.) from those threads. You MUST NOT
  directly call asyncio primitives (put_nowait, create_task, etc.) from these
  callbacks — doing so causes race conditions or segfaults due to GIL
  interaction with the asyncio event loop.

  The correct pattern:
    loop.call_soon_threadsafe(queue.put_nowait, data)
    loop.call_soon_threadsafe(loop.create_task, coroutine())

  asyncio.Queue is used for audio bridging (same pattern as AudioInput
  wrapping PyAudio in voice/audio_io.py).

Install notes:
  pjsua2 is a system-level C extension — it cannot be installed via pip alone.
  Recommended: use the backend Docker container.

  To build manually:
    1. Download PJSIP source: https://www.pjsip.org/download.htm
    2. ./configure && make dep && make
    3. cd pjsip-apps/src/swig/python && make && python3 setup.py install

  Or use a pre-built Docker image: pjsip/pjsua2 (check Docker Hub).

Config keys (from settings.json telephony.pjsip):
  sip_server    — SIP server hostname or IP (e.g. "192.168.1.10")
  sip_username  — SIP account username (extension number, e.g. "1001")
  sip_password  — SIP account password
  sip_port      — SIP server port (default: 5060)
"""

import asyncio
import time
import uuid
from typing import Optional, AsyncIterator

from telephony.base import BaseTelephonyProvider, CallInfo, CallState


# ---------------------------------------------------------------------------
# PJSIP bridge classes (defined at import time, pjsua2 loaded lazily)
# ---------------------------------------------------------------------------

class _INARACall:
    """
    Wraps a pjsua2.Call and bridges its audio + state callbacks
    into asyncio-safe queues via call_soon_threadsafe.
    """

    def __init__(self, pj_call_cls, account, call_id: str, loop: asyncio.AbstractEventLoop):
        self._call_id = call_id
        self._loop = loop
        # recv: phone audio → INARA (inbound PCM from remote party)
        self._recv_queue: asyncio.Queue = asyncio.Queue()
        # send: INARA audio → phone (outbound PCM to remote party)
        self._send_queue: asyncio.Queue = asyncio.Queue()
        self._audio_port = None  # _INARAMediaPort instance
        self._pj_call = None

    def setup(self, pj_call, media_port_cls):
        self._pj_call = pj_call
        self._audio_port = media_port_cls(
            call_id=self._call_id,
            recv_queue=self._recv_queue,
            send_queue=self._send_queue,
            loop=self._loop,
        )

    @property
    def recv_queue(self) -> asyncio.Queue:
        return self._recv_queue

    @property
    def send_queue(self) -> asyncio.Queue:
        return self._send_queue

    def hangup(self):
        if self._pj_call:
            try:
                self._pj_call.hangup()
            except Exception:
                pass


def _build_pjsip_classes():
    """
    Build pjsua2 subclasses at runtime after pjsua2 is confirmed importable.
    Returns (AccountClass, CallClass, MediaPortClass) or raises ImportError.
    """
    import pjsua2 as pj

    class _MediaPort(pj.AudioMediaPort):
        """
        Custom AudioMediaPort that bridges PJSIP audio frames to asyncio queues.

        onFrameReceived: PJSIP → recv_queue (remote party audio → INARA)
        onFrameRequested: send_queue → PJSIP (INARA audio → remote party)

        Both callbacks fire from PJSIP C++ threads.
        We use call_soon_threadsafe to safely push data into asyncio.
        """

        def __init__(self, call_id: str, recv_queue: asyncio.Queue,
                     send_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
            super().__init__()
            self._call_id = call_id
            self._recv_queue = recv_queue
            self._send_queue = send_queue
            self._loop = loop
            self._silence = bytes(320)  # 160 samples × 2 bytes, 16kHz 20ms frame

        def onFrameReceived(self, frame):
            """Called by PJSIP thread — push PCM bytes to recv_queue safely."""
            data = bytes(frame.buf)
            self._loop.call_soon_threadsafe(
                self._recv_queue.put_nowait, data
            )

        def onFrameRequested(self, frame):
            """Called by PJSIP thread — pull PCM bytes from send_queue."""
            try:
                data = self._send_queue.get_nowait()
            except asyncio.QueueEmpty:
                data = self._silence  # Send silence if nothing queued

            frame.buf = pj.ByteVector(data)
            frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO

    class _INARAPJCall(pj.Call):
        """
        pjsua2.Call subclass that routes state changes and media into
        our provider via call_soon_threadsafe.
        """

        def __init__(self, acc, call_id_str: str,
                     on_state: callable, on_media: callable,
                     loop: asyncio.AbstractEventLoop,
                     call_id: int = pj.PJSUA_INVALID_ID):
            super().__init__(acc, call_id)
            self._call_id_str = call_id_str
            self._on_state = on_state
            self._on_media = on_media
            self._loop = loop
            self._media_port = None

        def onCallState(self, prm):
            """PJSIP thread — bridge state change to asyncio."""
            info = self.getInfo()
            self._loop.call_soon_threadsafe(
                self._on_state, self._call_id_str, info.state
            )

        def onCallMediaState(self, prm):
            """PJSIP thread — connect audio when media is active."""
            info = self.getInfo()
            for mi in info.media:
                if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                    self._loop.call_soon_threadsafe(
                        self._on_media, self._call_id_str, self
                    )

    class _INARAAccount(pj.Account):
        """pjsua2.Account subclass that handles inbound calls."""

        def __init__(self, on_incoming: callable, loop: asyncio.AbstractEventLoop,
                     call_cls):
            super().__init__()
            self._on_incoming = on_incoming
            self._loop = loop
            self._call_cls = call_cls

        def onIncomingCall(self, prm):
            """PJSIP thread — bridge incoming call notification to asyncio."""
            call = self._call_cls(
                acc=self,
                call_id_str=str(uuid.uuid4()),
                on_state=None,   # Set properly in on_incoming handler
                on_media=None,
                loop=self._loop,
                call_id=prm.callId,
            )
            self._loop.call_soon_threadsafe(
                self._on_incoming, call
            )

    return _INARAAccount, _INARAPJCall, _MediaPort


# ---------------------------------------------------------------------------
# PJSIP Provider
# ---------------------------------------------------------------------------

class PJSIPProvider(BaseTelephonyProvider):
    """
    PJSIP/pjsua2 telephony provider for INARA homelab setup.

    Registers with your SIP PBX (Asterisk/FreePBX) and handles
    both inbound and outbound SIP calls.

    Audio is bridged via _INARAMediaPort (custom AudioMediaPort) using
    asyncio.Queue for thread-safe PCM exchange between PJSIP threads
    and the asyncio event loop.
    """

    def __init__(self):
        self._config: dict = {}
        self._ep = None          # pjsua2.Endpoint
        self._account = None     # _INARAAccount instance
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # call_id_str → _INARACall
        self._calls: dict[str, _INARACall] = {}
        # call_id_str → CallInfo
        self._call_infos: dict[str, CallInfo] = {}

        self.on_incoming_call = None
        self.on_call_state_changed = None

        # pjsua2 classes (built after import check)
        self._AccountCls = None
        self._CallCls = None
        self._MediaPortCls = None

    @property
    def name(self) -> str:
        return "pjsip"

    async def initialize(self, config: dict) -> None:
        pjsip_cfg = config.get("pjsip", {})
        self._config = pjsip_cfg
        self._loop = asyncio.get_running_loop()

        sip_server = pjsip_cfg.get("sip_server", "")
        sip_username = pjsip_cfg.get("sip_username", "")
        sip_password = pjsip_cfg.get("sip_password", "")
        sip_port = pjsip_cfg.get("sip_port", 5060)

        if not sip_server or not sip_username:
            print("[INARA] [PJSIP] WARNING: sip_server/sip_username not set.")
            return

        try:
            self._AccountCls, self._CallCls, self._MediaPortCls = _build_pjsip_classes()
        except ImportError:
            raise RuntimeError(
                "pjsua2 not installed. PJSIP requires building from source. "
                "See backend/telephony/pjsip_provider.py for install instructions."
            )

        import pjsua2 as pj

        # Initialize PJSIP endpoint
        self._ep = pj.Endpoint()
        self._ep.libCreate()

        ep_cfg = pj.EpConfig()
        ep_cfg.uaConfig.maxCalls = 8
        ep_cfg.logConfig.level = 3
        self._ep.libInit(ep_cfg)

        # UDP transport
        transport_cfg = pj.TransportConfig()
        transport_cfg.port = 0  # Let PJSIP pick a port
        self._ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, transport_cfg)

        self._ep.libStart()

        # Register SIP account
        acc_cfg = pj.AccountConfig()
        acc_cfg.idUri = f"sip:{sip_username}@{sip_server}"
        acc_cfg.regConfig.registrarUri = f"sip:{sip_server}:{sip_port}"

        cred = pj.AuthCredInfo("digest", "*", sip_username, 0, sip_password)
        acc_cfg.sipConfig.authCreds.append(cred)

        self._account = self._AccountCls(
            on_incoming=self._on_incoming_call_sync,
            loop=self._loop,
            call_cls=self._CallCls,
        )
        self._account.create(acc_cfg)

        print(f"[INARA] [PJSIP] Registered as sip:{sip_username}@{sip_server}:{sip_port}")

    async def make_call(self, number: str, purpose: Optional[str] = None) -> CallInfo:
        if not self._account:
            raise RuntimeError("PJSIP account not initialized.")

        import pjsua2 as pj

        call_id_str = str(uuid.uuid4())
        call_info = CallInfo(
            call_id=call_id_str,
            direction="outbound",
            remote_number=number,
            state=CallState.RINGING,
            started_at=time.time(),
        )
        self._call_infos[call_id_str] = call_info

        bridge = _INARACall(
            pj_call_cls=self._CallCls,
            account=self._account,
            call_id=call_id_str,
            loop=self._loop,
        )
        self._calls[call_id_str] = bridge

        sip_server = self._config.get("sip_server", "")
        pj_call = self._CallCls(
            acc=self._account,
            call_id_str=call_id_str,
            on_state=self._on_call_state_sync,
            on_media=self._on_media_active_sync,
            loop=self._loop,
        )
        bridge.setup(pj_call, self._MediaPortCls)

        call_prm = pj.CallOpParam(withMedia=True)
        pj_call.makeCall(f"sip:{number}@{sip_server}", call_prm)

        return call_info

    async def answer_call(self, call_id: str) -> None:
        bridge = self._calls.get(call_id)
        if bridge and bridge._pj_call:
            import pjsua2 as pj
            prm = pj.CallOpParam()
            prm.statusCode = 200
            bridge._pj_call.answer(prm)

    async def hang_up(self, call_id: str) -> None:
        bridge = self._calls.get(call_id)
        if bridge:
            bridge.hangup()
        self._on_call_ended(call_id)

    async def hold(self, call_id: str) -> None:
        bridge = self._calls.get(call_id)
        if bridge and bridge._pj_call:
            import pjsua2 as pj
            bridge._pj_call.setHold(pj.CallOpParam())
        info = self._call_infos.get(call_id)
        if info:
            info.state = CallState.ON_HOLD
            if self.on_call_state_changed:
                self.on_call_state_changed(info)

    async def unhold(self, call_id: str) -> None:
        bridge = self._calls.get(call_id)
        if bridge and bridge._pj_call:
            import pjsua2 as pj
            bridge._pj_call.reinvite(pj.CallOpParam())
        info = self._call_infos.get(call_id)
        if info and info.state == CallState.ON_HOLD:
            info.state = CallState.CONNECTED
            if self.on_call_state_changed:
                self.on_call_state_changed(info)

    async def send_audio(self, call_id: str, audio_data: bytes) -> None:
        bridge = self._calls.get(call_id)
        if bridge:
            self._loop.call_soon_threadsafe(
                bridge.send_queue.put_nowait, audio_data
            )

    async def receive_audio(self, call_id: str) -> AsyncIterator[bytes]:
        bridge = self._calls.get(call_id)
        if not bridge:
            return

        while True:
            chunk = await bridge.recv_queue.get()
            if chunk is None:  # Sentinel: call ended
                break
            yield chunk

    def get_call_state(self, call_id: str) -> Optional[CallInfo]:
        return self._call_infos.get(call_id)

    async def shutdown(self) -> None:
        for call_id in list(self._calls.keys()):
            bridge = self._calls.get(call_id)
            if bridge:
                bridge.hangup()

        if self._ep:
            try:
                self._ep.libDestroy()
            except Exception:
                pass
            self._ep = None

    # -----------------------------------------------------------------------
    # Internal: PJSIP callbacks (called from PJSIP threads via call_soon_threadsafe)
    # -----------------------------------------------------------------------

    def _on_incoming_call_sync(self, pj_call):
        """
        Registered as callback on _INARAAccount.onIncomingCall.
        Called via call_soon_threadsafe — runs in asyncio thread.
        """
        import pjsua2 as pj

        call_id_str = str(uuid.uuid4())
        info = pj_call.getInfo()
        from_uri = str(info.remoteUri)
        # Extract number from SIP URI sip:1001@192.168.1.10
        number = from_uri.split(":")[1].split("@")[0] if ":" in from_uri else from_uri

        call_info = CallInfo(
            call_id=call_id_str,
            direction="inbound",
            remote_number=number,
            state=CallState.RINGING,
            started_at=time.time(),
        )
        self._call_infos[call_id_str] = call_info

        bridge = _INARACall(
            pj_call_cls=self._CallCls,
            account=self._account,
            call_id=call_id_str,
            loop=self._loop,
        )
        # Patch the pj_call with proper state/media callbacks
        pj_call._call_id_str = call_id_str
        pj_call._on_state = self._on_call_state_sync
        pj_call._on_media = self._on_media_active_sync
        bridge.setup(pj_call, self._MediaPortCls)
        self._calls[call_id_str] = bridge

        if self.on_incoming_call:
            self.on_incoming_call(call_info)

    def _on_call_state_sync(self, call_id_str: str, pj_state: int):
        """
        Called via call_soon_threadsafe when PJSIP call state changes.
        Maps pjsua2 PJSIP_INV_STATE_* to our CallState enum.
        """
        try:
            import pjsua2 as pj
            state_map = {
                pj.PJSIP_INV_STATE_CALLING:     CallState.RINGING,
                pj.PJSIP_INV_STATE_INCOMING:     CallState.RINGING,
                pj.PJSIP_INV_STATE_EARLY:        CallState.RINGING,
                pj.PJSIP_INV_STATE_CONNECTING:   CallState.RINGING,
                pj.PJSIP_INV_STATE_CONFIRMED:    CallState.CONNECTED,
                pj.PJSIP_INV_STATE_DISCONNECTED: CallState.ENDED,
            }
            new_state = state_map.get(pj_state, CallState.IDLE)
        except Exception:
            new_state = CallState.IDLE

        info = self._call_infos.get(call_id_str)
        if not info:
            return

        info.state = new_state

        if new_state == CallState.CONNECTED:
            info.started_at = time.time()

        if new_state == CallState.ENDED:
            info.ended_at = time.time()
            # Signal receive_audio iterator to stop
            bridge = self._calls.get(call_id_str)
            if bridge:
                self._loop.call_soon_threadsafe(
                    bridge.recv_queue.put_nowait, None
                )

        if self.on_call_state_changed:
            self.on_call_state_changed(info)

        if new_state == CallState.ENDED:
            self._calls.pop(call_id_str, None)
            self._call_infos.pop(call_id_str, None)

    def _on_media_active_sync(self, call_id_str: str, pj_call):
        """
        Called via call_soon_threadsafe when call media becomes active.
        Connects PJSIP's audio port to our custom MediaPort.
        """
        bridge = self._calls.get(call_id_str)
        if not bridge or not bridge._audio_port:
            return

        try:
            import pjsua2 as pj
            aud_med = pj_call.getAudioMedia(-1)  # Get first audio media
            bridge._audio_port.startTransmit(aud_med)
            aud_med.startTransmit(bridge._audio_port)
            print(f"[INARA] [PJSIP] Media connected for call {call_id_str}")
        except Exception as e:
            print(f"[INARA] [PJSIP] Media connect error: {e}")

    def _on_call_ended(self, call_id: str):
        """Clean up a call that has ended."""
        info = self._call_infos.get(call_id)
        if info and info.state != CallState.ENDED:
            info.state = CallState.ENDED
            info.ended_at = time.time()
            if self.on_call_state_changed:
                self.on_call_state_changed(info)

        bridge = self._calls.get(call_id)
        if bridge:
            # Signal receive_audio iterator to stop
            self._loop.call_soon_threadsafe(
                bridge.recv_queue.put_nowait, None
            )

        self._calls.pop(call_id, None)
        self._call_infos.pop(call_id, None)
