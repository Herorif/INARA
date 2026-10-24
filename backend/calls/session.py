"""One explicitly armed call. Fresh controls and ready media precede answer."""

import asyncio
import time

from services.tools import ServiceError


class CallSession:
    def __init__(self, profile, control, audio, voice_factory, records):
        self.profile, self.control, self.audio = profile, control, audio
        self.voice_factory, self.records = voice_factory, records
        self.tasks = []
        self.observation = None
        self.answer_attempted = False
        self.active_view = None
        self.active_fingerprint = None
        self.record = None
        self.key = None

    async def run(self, arm_seconds=30):
        if not self.profile.route_confirmed or not self.profile.controls_confirmed:
            raise ServiceError("call_not_enrolled", "Prove the two-way route and control lifecycle before arming.")
        deadline = time.monotonic() + min(max(arm_seconds, 1), 120)
        while True:
            self.observation = await self.control.observe()
            if self.observation.state == "ringing":
                break
            if self.observation.state != "absent":
                raise ServiceError("call_ambiguous", "Another or ambiguous call is present. Leave it untouched.")
            if time.monotonic() >= deadline:
                raise ServiceError("call_arm_expired", "No incoming call arrived during this one-call lease.")
            await asyncio.sleep(0.5)
        self.key, self.record = self.records.claim(self.profile.channel, self.observation)
        state, code = "failed", "call_preparation_failed"
        try:
            # Open and validate the dedicated devices before invoking Answer.
            await asyncio.wait_for(self.audio.open(), 8)
            async with asyncio.timeout(self.profile.max_seconds):
                async with self.voice_factory() as voice:
                    fresh = await self.control.observe()
                    if fresh != self.observation:
                        raise ServiceError("call_stale", "The incoming call changed while preparing.")
                    self.active_view = fresh.view_id
                    self.answer_attempted = True  # Never retry even if Invoke/ACK is lost.
                    await self.control.answer(fresh)
                    for _ in range(10):
                        current = await self.control.observe()
                        if not self.same_caller(current):
                            raise ServiceError("call_changed", "The call identity changed after answering.")
                        if current.state == "active":
                            self.active_view, self.active_fingerprint = current.view_id, current.fingerprint
                            break
                        if current.state != "ringing":
                            raise ServiceError("call_answer_uncertain", "The call connection could not be established.")
                        await asyncio.sleep(0.25)
                    else:
                        raise ServiceError("call_answer_uncertain", "Answer outcome is uncertain; no retry.")
                    self.record["state"] = "active"
                    self.records.progress(self.key, self.record)
                    # Discard frames captured while the client was still ringing.
                    if hasattr(self.audio, "frames"):
                        while not self.audio.frames.empty():
                            self.audio.frames.get_nowait()
                    if hasattr(self.audio, "activate"):
                        self.audio.activate()
                    await voice.greet()
                    self.tasks = [asyncio.create_task(self.send(voice)),
                                  asyncio.create_task(self.receive(voice)),
                                  asyncio.create_task(self.watch())]
                    done, _ = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                    if self.tasks[2] not in done:
                        raise ServiceError("call_stream_ended", "A call stream ended before the call client.")
                    state, code = "completed", None
        except asyncio.CancelledError:
            state, code = "interrupted", "owner_stopped"
            raise
        except TimeoutError:
            state, code = "interrupted", "call_time_limit"
        except Exception as exc:
            state = "uncertain" if self.answer_attempted else "failed"
            code = exc.code if isinstance(exc, ServiceError) else "call_bridge_failed"
        finally:
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            self.tasks.clear()
            if self.answer_attempted:
                try:
                    current = await asyncio.wait_for(self.control.observe(), 5)
                    if (current.state == "active" and self.same_caller(current)
                            and (self.active_fingerprint is None or current.fingerprint == self.active_fingerprint)):
                        await asyncio.wait_for(self.control.hangup(current), 5)
                        after = await asyncio.wait_for(self.control.observe(), 5)
                        if after.state != "ended" or not self.same_caller(after):
                            state, code = "uncertain", "call_hangup_uncertain"
                    elif current.state != "ended" or not self.same_caller(current):
                        state, code = "uncertain", "call_handoff_required"
                except Exception:
                    state, code = "uncertain", "call_hangup_uncertain"
            try:
                await asyncio.wait_for(self.audio.close(), 5)
            except Exception:
                state, code = "uncertain", "call_cleanup_failed"
            self.record.update(state=state, code=code)
            self.records.finish(self.key, self.record)
        return self.record

    def same_caller(self, current):
        return (current.caller_hash == self.observation.caller_hash
                and current.process_start == self.observation.process_start
                and (self.active_view is None or current.view_id == self.active_view))

    async def send(self, voice):
        while True:
            data = await self.audio.read()
            if len(data) != 640:
                raise ServiceError("call_audio_format", "Expected one 20ms caller PCM frame.")
            await asyncio.wait_for(voice.send(data), 3)

    async def receive(self, voice):
        total = 0
        async for event in voice.events():
            if event["kind"] == "audio":
                await self.audio.write(event["data"])
            elif event["kind"] == "interrupted":
                await self.audio.clear()
            elif event["kind"] == "transcript":
                text, role = event["text"], event["role"]
                if role not in ("caller", "assistant") or not isinstance(text, str):
                    raise ServiceError("call_transcript_invalid", "Invalid transcript event.")
                total += len(text)
                if total > 12000 or len(self.record["transcript"]) >= 200:
                    raise ServiceError("call_transcript_limit", "Call transcript capacity reached.")
                self.record["transcript"].append({"role": role, "text": text})
                self.records.progress(self.key, self.record)

    async def watch(self):
        while True:
            await asyncio.sleep(0.5)
            current = await self.control.observe()
            if current.state == "ended" and self.same_caller(current):
                return
            if current.state == "absent":
                raise ServiceError("call_view_lost", "The call view disappeared; termination is unverified.")
            if (current.state != "active" or not self.same_caller(current)
                    or current.fingerprint != self.active_fingerprint):
                raise ServiceError("call_changed", "The active call changed; stop this session.")
