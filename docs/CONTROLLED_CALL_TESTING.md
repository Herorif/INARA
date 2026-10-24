# Controlled one-call test preparation

Step 5, 24 October 2026: the software workflow is implemented. **Live answering remains locked.** `config/call-test-policy.json` is disabled and the backend has no installed physical evidence collector. Changing the policy alone cannot enable calls. No phone, microphone, speaker, call client, model or real worker was activated during this implementation.

## Workflow

The desktop Call Lab now contains a controlled-test panel. It saves an observed `BridgeProfile` as an encrypted owner/project draft, shows readiness blockers and requests an explicit review. Imported `route_confirmed` and `controls_confirmed` flags must both be false. A pasted profile is configuration, never physical proof.

Only after an owned physical capture and all policy/resource checks pass can a review issue a one-use token. Reviews expire after 60 seconds and belong to the originating authenticated owner workspace, project, draft revision and capture. The operator must type `ANSWER ONE CONTROLLED TEST CALL`. Arming waits at most 30 seconds for one incoming call, uses the existing bounded core admission/supervisor and local structured English speech, and consumes the review even if the outcome is refused or its acknowledgement is lost. There is no automatic retry or queue.

Stop remains available while the arm acknowledgement is pending, using the request UUID retained before transmission. Backend disconnect, lock, project change, resource restriction and application shutdown stop owned work. Panel cleanup also requests Stop when connected. Connection loss can make cleanup uncertain; it cannot guarantee a remote phone hangup, and the operator must inspect the call client in that situation. The supervisor continues to enforce its own limits.

## Evidence boundary

`ControlledCalls.collector` is deliberately unset. Its future backend integration must observe actual controls, caller-to-assistant receive audio, assistant-to-caller transmit audio, isolation, Stop and disconnect behavior. It must bind the observed process/window/endpoint profile to the owner/project, current draft revision, exact source and helper hashes, capture UUID and short monotonic lifetime (maximum ten minutes). The recurring admission callback rechecks those bindings throughout the lease.

`CapturedEvidence` is an internal typed collector result, not hardware attestation. Hashes only bind inputs; they do not demonstrate duplex audio or successful call control. There is no renderer evidence-upload endpoint, evidence import, policy-toggle RPC, model-selection parameter or public way to mark tests passed. Tests inject synthetic collector results and inert supervisors to verify rejection and lifetime behavior; those fixtures are not physical acceptance.

## Remaining acceptance

1. In the owner's later device session, connect the actual Fold/host and implement the trusted physical capture integration against the selected supported control/audio route. Establish what each SIM and personal WhatsApp client actually permits. Do not presume universal carrier or personal-account call access.
2. Verify dedicated audio routing and control identity, then test receive/transmit/isolation, Stop/disconnect and process/endpoint changes using a second caller. A failing or unavailable route stays blocked.
3. Only after evidence review, explicitly configure the local test policy and prepare a new source-bound draft. Run one controlled call per review, inspect protected receipts and verify no background rearming occurs. Repeat separately for SIM and personal WhatsApp.
4. Complete Android installation/pairing, receipt grant/cache/privacy/device lifecycle acceptance and later distribution acceptance. Existing Order 4 debug APK is unchanged by this desktop/backend step.

The real local-model benchmark remains owner-deferred for insufficient RAM; retain its 7 GiB guard and keep the candidate unloaded/unaccepted. Production policies remain disabled, 52 controller and 85 desktop review subjects remain pending, and game/Legion sustained-use acceptance remains open. WhatsApp replies, acknowledgements, notification actions, outgoing calls, forwarding and Business migration remain excluded. See [deferred work](DEFERRED_WORK.md) and [release gates](RELEASE_GATES.json).

## Verification

304 focused Python tests (24 new controlled-workflow cases), 14 client checks (five new workflow checks), scoped Ruff, TypeScript, generated-contract drift and production Vite build are recorded in [execution evidence](qa/controlled-call-workflow-verification.json). UI compilation is not visual/device acceptance. No Android rebuild was necessary because Android sources were unchanged.
