# Order 3: optional local model integration

Implemented 24 October 2026. **Code integration and actual installation are complete; real quality/performance acceptance is owner-deferred because sufficient RAM cannot be freed.** [QA](qa/local-model-verification.json) records 174 passing focused Python checks (25 new model checks), five client checks, scoped Ruff, TypeScript, contract drift, production Vite build and pip dependency consistency.

The first real evaluation refused to load at 1.81 GiB available RAM; the later check had 2.24 GiB. This is a capacity refusal, not a model benchmark failure or a measured quality result. No other applications were stopped. The guard remains 7 GiB available. `accepted_for_calls=false`; no inference latency, peak runtime RAM or actual model quality is claimed yet. The owner confirmed on 24 October 2026 that sufficient resources cannot be freed. The benchmark is explicitly deferred; retain the guard and keep model mode unaccepted/unloaded. Structured local message-taking remains the default. Resume the evaluation only when the owner has resources available; do not repeatedly request that applications be closed.

## Selected candidate and installation

The first candidate is the official [Qwen3 4B Q4_K_M GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF), commit `bc640142c66e1fdd12af0bd68f40445458f3869b`, using a pinned [llama.cpp](https://github.com/ggml-org/llama.cpp/releases/tag/b11669) portable Windows CPU runtime. This is a bounded message-taking candidate, not a newest/best-model claim or a frontier coding assistant replacement. Model selection can change after actual quality/performance comparison. Ollama and a permanent inference service are not required.

The 2,497,280,256-byte model matches upstream LFS SHA-256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`. The runtime ZIP matches GitHub's published asset digest `37b3efcf962847ca869745fd4ccf7f5e7e8dacfeff9fa3523b4ca8cdc66d632b`. [Pinned manifest](../config/local-call-model.json) records URLs/size/revisions. Checksum verification over HTTPS is not a signed supply-chain attestation. Model/runtime redistribution and native component review remain separate from existing controller/desktop ledgers.

The explicit setup helper validates downloads, safe ZIP extraction and runtime inventory. A stalled direct transfer was preserved, then bounded exact-range downloads assembled and SHA-256 verified the model. Verified numbered transfer chunks were removed after the full model existed; the interrupted partial is retained. Local model/runtime files occupy about 2.5 GB plus that retained interrupted download. No global installation, PATH change, startup service, account login or firewall rule was added. The optional Python measurement extra is `psutil==7.2.2`; the existing `httpx==0.28.1` is reused.

## Behavior and limits

Structured Vosk/SAPI message-taking remains the default. Explicit internal `dialogue_mode=model` additionally requires a current passing real-evaluation receipt. It reserves CPU2/RAM6144MiB/VRAM0 in the shared governor, refuses competing work and resident/gaming states, and requires the separate trusted physical acceptance check from Order 2. A JSON/profile/renderer flag cannot grant that physical acceptance. The public UI still exposes only offline bridge checks; no public live-start route is enrolled.

Inference is session-scoped: verify installed model/runtime hashes, start one loopback-only process with a random authentication key, two CPU threads, a 2,048-token context and 160-token output limit, then terminate it on exit or cancellation. The core call worker's existing Windows Job Object also owns its descendants. Runtime proxy/provider/agent environment variables are not inherited; client proxy inheritance, redirects, built-in runtime tools/agents and web UI are disabled. Inference uses local files, never an automatic download or cloud fallback. These are admission/configuration limits, not hard RAM/CPU or network-isolation sandboxes. Explicit developer evaluation/preview commands are separate from resident scheduling.

The model interprets a current utterance as an answer, repeat request, identity question, decline or unrelated action request. A field value must be a bounded **exact substring** of that utterance. Invented/paraphrased fields and invalid JSON do not advance the dialogue. Identity/repeat questions no longer need to be stored as the caller's name when the evaluated interpreter is selected. The deterministic controller still owns field order, readback and literal yes/no confirmation; the model cannot confirm on the caller's behalf, access owner history/files, execute tools, send replies or make commitments. Failure asks the caller to repeat using local scripted speech. Recognition, caller acoustics and message-taking accuracy remain physical-test concerns.

This integration offers bounded call interpretation and an explicit tool-free text preview. It does not replace desktop chat's provider configuration, implement unrestricted autonomous reasoning, enable 3D/image models, add natural speech interruption or establish multilingual quality. The voice path remains English and half-duplex.

## Commands and real acceptance

```powershell
# Metadata only; does not load weights or start a server.
.venv/Scripts/python.exe scripts/call-model.py preflight

# Explicit installation only, already performed for this candidate.
.venv/Scripts/python.exe -m pip install -r requirements-call-model.txt
.venv/Scripts/python.exe scripts/setup-call-model.py

# After freeing at least 7 GiB RAM: synthetic real-inference benchmark.
.venv/Scripts/python.exe scripts/call-model.py evaluate

# Optional local text preview; no tools or private memory and no phone access.
'Explain how to measure a cube for a 3D model.' | .venv/Scripts/python.exe scripts/call-model.py chat
```

Evaluation runs eight synthetic actual-inference cases covering name/reason/message/callback extraction, repeat/identity/decline handling and an instruction-injection request. All must pass; startup must be <=30 seconds, every turn <=8 seconds and sampled runtime RSS <=4 GiB. The report includes timings, sampled process RSS and shutdown verification. It exits unsuccessfully when quality/performance does not pass. This narrow suite does not establish general intelligence, adversarial robustness, real caller quality, gaming coexistence or battery acceptance.

A passing local workflow receipt is bound to the pinned manifest, installation inventory and exact model/interpreter/voice/evaluator source hashes. Changes make it stale. Runtime integrity is checked again before launch. These receipts are unsigned owner-local workflow evidence, not tamper-proof attestations. Evaluation/preview output is explicit; prompts and responses are not written to runtime logs by the inference wrapper.

## Remaining work

Order 3 remains pending real inference acceptance until enough RAM is free. If the candidate fails, record its actual result and choose/tune another candidate rather than silently accepting it. Order 4 protected mobile receipt sync is now integrated and compiled; physical phone delivery/cache acceptance remains pending. Phone pairing/install, isolated audio routes and exact personal SIM/WhatsApp controls remain for the owner's later controlled call session. WhatsApp text actions, outgoing calls, forwarding and Business migration stay excluded. Production signing/custody, 52 controller and 85 desktop reviews, other providers/models/devices and game/soak measurements remain tracked in [deferred work](DEFERRED_WORK.md).
