# R6 quick assistant and reviewed speech

Implemented 19 October 2026 as one milestone. R7 secure Android pairing is next. This completes the bounded implementation and fixture acceptance; physical speech/provider acceptance remains deferred.

## Everyday flow

Ctrl+Shift+Space opens the native compact assistant (approximately 520 x 740); the tray still opens the full workspace. Quick assistant is also available from the hero action and command palette. The surface is lazy-loaded, has keyboard/pointer controls, readable JARVIS styling, reduced-motion support, a draggable desktop header and responsive widths verified at 390/520/768 pixels. Expanding returns to the full workspace. Closing destroys the workspace and returns to the native resident.

Typed messages use the existing scoped conversation/history and remain independent of microphone preparation. Interrupt cancels origin typed work. In gaming mode typed input remains available and speech capture is disabled. Starting quick mode closes feature panels through their existing cleanup paths.

Voice is deliberately explicit:

1. **Prepare voice** checks configuration and requests the existing `start_audio` permission through the common dispatcher. Preparation opens no microphone or provider client.
2. **Hold to talk** acquires the selected browser microphone and one AudioContext/worklet. Release immediately stops tracks and the context before transcription starts. Releasing during acquisition cancels and releases a late permission grant.
3. **Transcribing** sends the bounded WAV to the configured optional transcription adapter after release. Partial transcript updates stream during recognition; this is not continuous live recognition while recording.
4. **Review** permits editing. Recognition does not invoke tools or submit the transcript to the conversation automatically.
5. **Send** calls the existing ConversationService with the same dispatcher/catalog, project containment, owner authorization, approvals and durable request claims as typed input. Raw PCM and unsent transcripts are not written to history. Successfully submitted text follows normal encrypted conversation persistence.
6. Optional **Speak voice answers** selects an already available `localService` speech-synthesis voice. It defaults off, selects no cloud voices and installs nothing. Interrupt stops it; lack of a local voice leaves the answer readable.

## Ownership and bounds

`services/speech.py` owns one origin-SID/owner/project/conversation/turn-scoped session. The renderer capture module owns the physical stream and AudioContext; its controller owns subscriptions, acknowledgements, frame delivery and local playback. The core never opens a microphone. There is no wake-word listener.

The media contract is mono signed little-endian PCM16 at 16 kHz, 20 ms / 640 bytes per frame, sequence 0-999 and timestamps exactly sequence x 20 ms. Strict metadata rejects coercion, malformed/oversized payloads, missing/duplicate/out-of-order frames and foreign turns. PCM is capped at 640,000 bytes (20 seconds). The renderer permits eight queued frames plus one in flight and cancels on backpressure or a three-second ACK deadline. It retains no recording across cancellation or reconnect.

Preparation expires in the renderer after 20 seconds. The server additionally bounds the total turn to 120 seconds, recording from its first frame to 22 seconds, stalled listening to 15 seconds at the next operation, and transcription to 40 seconds. Provider cleanup has a five-second deadline. The browser request may outlast the logical turn; a late grant is stopped without reattaching. No uncertain transcription, conversation or tool action is replayed automatically.

Owner/role, current project, face authentication, start_audio denial and resource state are rechecked through the turn and before/after provider work and tool approval. Source changes/loss, hidden/blurred renderer, native minimize/suspend/lock signals, explicit interruption, panel/core closure, origin disconnect and gaming/resident restrictions release or invalidate speech. Pending capture approval is task-owned and cancelled too; its matching popup is cleared without affecting another action's approval.

Five strict `speech_*` routes and owner-gated `cancel_conversation` are additive UI-contract-v1 changes. Pydantic generates the speech TypeScript/schema files. Inventory: **63 socket routes, 55 tools, 40 model-visible tools**. The hidden `speech_capture` tool cannot be selected by the model. The 37 old voice aliases remain dormant compatibility policy fixtures, rather than a second production voice catalog.

## Retired paths and configuration

The old `inara.AudioLoop` and `voice.pipeline.VoicePipeline` constructors now fail with `voice_migrated` and guidance to open Quick assistant. Their two always-on audio/provider loops were removed. The voice namespace no longer eagerly imports audio/camera helpers. Retained WorkspaceService/VoiceBridge tests inject legacy fixtures to preserve compatibility-policy evidence; they do not establish a running legacy microphone path.

No key, model, device or dependency was configured or installed. The optional adapter lazy-loads the existing Google SDK only after a completed recording. `INARA_TRANSCRIPTION_MODEL` can independently select an audio-capable model later; otherwise it inherits `INARA_TEXT_MODEL`. Existing model defaults were preserved, not validated against the provider. Missing key/SDK fails before microphone acquisition. Ordinary typed AI answers still require their separately deferred text-provider configuration.

## Verification and limits

The regression suite, semantic TypeScript check, generated-contract drift check, Ruff and production build pass; **733 Python tests and 60 Node checks pass, with one Blender skip**. The final two speech cleanup refinements also pass the focused 29 Python / eight Node speech checks. CI includes the new speech checks and native fixture runner, but hosted CI has not run in this session. Existing build warnings concern Vite's CJS API, stale Browserslist data and the lazy CAD chunk size.

Python speech fixtures verify strict PCM validation, ordered frames, transcript review, same-dispatcher tool denial, provider WAV/stream/cleanup, owner/project/resource/permission changes, pending-approval cancellation, origin interruption and root disconnect/restriction/shutdown. Node fixtures verify PCM resampling/framing, local-only synthesis, bounded delivery, late ACK/permission rejection, device-loss cleanup, microphone exclusivity and interruption during acquisition. No physical audio device or external provider is exercised by those tests.

[Native integration report](qa/r6-speech-verification.json) and [renderer report](qa/r6-speech-ui-verification.json) pass on the actual final Electron build. Synthetic Web Audio enters the real bundled AudioWorklet; injected server recognition/conversation responses are visibly labelled fixtures. Checks cover unconfigured preparation making zero getUserMedia calls, hold/release, review/edit/Send, origin conversation display, track termination, suspend cleanup, responsive layout and real native quick/full focus routing. Screenshots: [compact desktop](qa/r6-quick-desktop.png), [mobile width](qa/r6-quick-mobile.png), [review](qa/r6-quick-review.png).

After workspace closure the final run found no speech turn, pending speech approval or heavy model modules; graceful core shutdown passed. Six short post-close resident working-set samples were **66.46-66.47 MB**. This is a short fixture recovery measurement, not a real-game, voice latency, peak audio memory or long-duration idle benchmark. [Electron fallback lifecycle](qa/r6-fallback-verification.json) also passes close/reopen, reminder receipt, gaming and explicit quit.

Real microphone accuracy/latency, installed local voice playback, audio-capable model availability, background noise, Bluetooth/default-device switching, physical sleep/resume and OS hotkey collision behavior still require owner-device acceptance. No always-on/wake profile, Android pairing, call answering, WhatsApp drafting/sending, model downloads or real device/provider acceptance is claimed. Existing SIM/personal WhatsApp, deferred game benchmarking and other creative acceptance gates are preserved.
