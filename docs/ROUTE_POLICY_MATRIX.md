# Supported route/policy matrix (R2b1)

The [machine-readable inventory](ROUTE_POLICY_MATRIX.json) records every registered socket route, `/status`, shared tool and separate legacy voice declaration. Tests compare route/tool/declaration names with the supported source. Inventory coverage does not mean policy migration is complete. No mobile routes are enabled.

## Policy conventions

The existing persisted semantics are: `False` / `allow_within_scope` allows a validated shared action, `deny` rejects, and `True` or absent policy asks for owner approval. New local direct routes also require an authenticated renderer. Confirmations require actual booleans and the shared dispatcher binds approvals to the owner. Schema names describe current validation; legacy rows explicitly lack strict schemas.

## Socket routes

| Event | Schema | Caller and context | Policy | Effects | Response scope | Lifetime | Replacement and status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `acknowledge_reminder` | Legacy delivery_id mapping | Authenticated connected owner; role unrestricted; Registry owner; desktop-global reminder list; delivery IDs owner-bound | Authentication and store delivery ownership; receipt schema pending | acknowledge reminder | SID result/error; same-owner refresh | Dispatcher approval deadline; store transaction/lease | ReminderTransport; receipt schema/role policy review remains; **existing-partial** |
| `add_printer` | Legacy host/name/type/camera_url mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | Persist printer config and probe network | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `cad_artifact` | ArtifactRequest | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative artifact | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing** |
| `cad_cancel` | JobRequest | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative cancel | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing** |
| `cad_close` | Ignored optional mapping | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative close | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing** |
| `cad_list` | Ignored optional mapping | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative list | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing** |
| `cad_plan` | PlanRequest | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative plan | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing-partial** |
| `cad_submit` | BuildRequest | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative submit | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing** |
| `cancel_reminder` | ReminderAction | Authenticated connected owner; role unrestricted; Registry owner; desktop-global reminder list; delivery IDs owner-bound | Shared dispatcher mutation gates | cancel reminder | SID result/error; same-owner refresh | Dispatcher approval deadline; store transaction/lease | ReminderTransport; receipt schema/role policy review remains; **existing** |
| `confirm_tool` | Confirmation: strict id and boolean | Authenticated renderer; Registry owner; shared approval owner; voice fallback | Role/auth/strict input; shared owner-binding; voice fallback remains legacy | Resolve shared or legacy voice confirmation | Scoped errors; no success ACK | Dispatcher approval deadline; legacy voice separate | Shared confirmation transport; bind voice pending IDs in R6; **migrated-partial** |
| `connect` | Socket auth mapping; token/UUID validation | Launch-token client; native owner constrained; DesktopSessions principal/role; global project | Token, UUID and native-owner check; hydration partly before face gate | Register channel, hydrate state, optional face loop | SID state; auth events may broadcast | Socket lifecycle; optional face task remains legacy | DesktopSessions + future connection transport; **existing-partial** |
| `control_device` | ControlDevice | Authenticated renderer direct; authenticated owner via typed tools; Registry principal and immutable selected-project snapshot | Shared dispatcher per-tool denial/approval; recheck auth/denial after approval | control device | SID result/error; stamped bus events to owner renderers | Dispatcher approval deadline; 30s cooperative execution; origin disconnect/app close cancel | LocalActions / LocalActionTransport; **migrated** |
| `control_kasa` | Legacy ip/action/value mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | control kasa | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `create_reminder` | CreateReminder | Authenticated connected owner; role unrestricted; Registry owner; desktop-global reminder list; delivery IDs owner-bound | Shared dispatcher mutation gates | create reminder | SID result/error; same-owner refresh | Dispatcher approval deadline; store transaction/lease | ReminderTransport; receipt schema/role policy review remains; **existing** |
| `desktop_control` | Legacy action mapping validated by host | Workspace role; native owner check; NativeHost identity | Workspace role and native ownership | Register/open/close/gaming/quit | Scoped ACK; owner renderer disconnection | Native control timeout | R2b2 native transport schema; **existing-partial** |
| `disconnect` | Socket lifecycle SID | Transport lifecycle; Registry SID -> owner/role | No caller-provided identity | Cancel origin local actions; last-renderer jobs; final-owner approvals | No response | Application cleanup | Application.disconnect; **existing** |
| `discover_kasa` | Ignored optional mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | Discover network devices and persist device settings | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `discover_printers` | Ignored optional mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | Discover network printers; activate lazy monitor | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `dismiss_reminder` | Legacy delivery_id mapping | Authenticated connected owner; role unrestricted; Registry owner; desktop-global reminder list; delivery IDs owner-bound | Authentication and store delivery ownership; receipt schema pending | dismiss reminder | SID result/error; same-owner refresh | Dispatcher approval deadline; store transaction/lease | ReminderTransport; receipt schema/role policy review remains; **existing-partial** |
| `generate_cad` | Legacy prompt mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Heavy-resource gate only; no common direct-action authorization | generate cad | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `get_reminders` | Ignored optional mapping | Authenticated connected owner; role unrestricted; Registry owner; desktop-global reminder list; delivery IDs owner-bound | Authentication and store delivery ownership; receipt schema pending | get reminders | SID result/error; same-owner refresh | Dispatcher approval deadline; store transaction/lease | ReminderTransport; receipt schema/role policy review remains; **existing-partial** |
| `get_settings` | Ignored optional mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | Read settings/permissions | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | Next R2b2 authenticated settings/permission transport; **pending** |
| `get_slicer_profiles` | Ignored optional mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | get slicer profiles | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `get_system_info` | NoArguments | Authenticated renderer direct; authenticated owner via typed tools; Registry principal and immutable selected-project snapshot | Shared dispatcher per-tool denial/approval; recheck auth/denial after approval | get system info | SID result/error; stamped bus events to owner renderers | Dispatcher approval deadline; 30s cooperative execution; origin disconnect/app close cancel | LocalActions / LocalActionTransport; **migrated** |
| `get_tool_permissions` | Ignored optional mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | get tool permissions | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | Next R2b2 authenticated settings/permission transport; **pending** |
| `image_artifact` | ImageArtifactRequest | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative artifact | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing** |
| `image_cancel` | JobRequest | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative cancel | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing** |
| `image_close` | Ignored optional mapping | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative close | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing** |
| `image_list` | Ignored optional mapping | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative list | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing** |
| `image_submit` | ImageRequest | Authenticated renderer; Registry owner and resolved selected project | Shared generation permission on submit; owner/project checks; planner permission review pending | Creative submit | Scoped ACK/error; job events to owner renderers | Owned service/worker/planner cancellation and deadlines | Existing creative transport; planner policy review in R2b; **existing** |
| `iterate_cad` | Legacy prompt mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Heavy-resource gate only; no common direct-action authorization | iterate cad | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `launch_app` | LaunchApp | Authenticated renderer direct; authenticated owner via typed tools; Registry principal and immutable selected-project snapshot | Shared dispatcher per-tool denial/approval; recheck auth/denial after approval | launch app | SID result/error; stamped bus events to owner renderers | Dispatcher approval deadline; 30s cooperative execution; origin disconnect/app close cancel | LocalActions / LocalActionTransport; **migrated** |
| `list_all_devices` | NoArguments | Authenticated renderer direct; authenticated owner via typed tools; Registry principal and immutable selected-project snapshot | Shared dispatcher per-tool denial/approval; recheck auth/denial after approval | list all devices | SID result/error; stamped bus events to owner renderers | Dispatcher approval deadline; 30s cooperative execution; origin disconnect/app close cancel | LocalActions / LocalActionTransport; **migrated** |
| `pause_audio` | Ignored optional mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | pause audio | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `print_stl` | Legacy stl_path/printer/profile mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | Resolve file, preview, slice, upload/start printer job; containment/grant migration pending | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `prompt_web_agent` | Legacy prompt mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Heavy-resource gate only; no common direct-action authorization | prompt web agent | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `read_clipboard` | NoArguments | Authenticated renderer direct; authenticated owner via typed tools; Registry principal and immutable selected-project snapshot | Shared dispatcher per-tool denial/approval; recheck auth/denial after approval | read clipboard | SID result/error; stamped bus events to owner renderers | Dispatcher approval deadline; 30s cooperative execution; origin disconnect/app close cancel | LocalActions / LocalActionTransport; **migrated** |
| `resume_audio` | Ignored optional mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | resume audio | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `resume_conversation` | ResumeConversation | Authenticated connected owner; role unrestricted; Registry owner and captured selected project | Shared dispatcher tool gates; durable owner/project request scope | Restore protected history | Result/transcript/error or restore/failure to SID | Existing provider/tool deadlines; durable dedupe; bounded restore | ConversationTransport; role policy review remains; **existing** |
| `save_memory` | Legacy messages/filename mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | Write plaintext legacy memory file | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `set_resource_state` | ResourceRequest | Connected SID; role unrestricted; Global governor; native gaming override | Connected identity; no shared permission | Change mode and close jobs/media | Broadcast resource_state; invalid input ignored | Legacy adapter/task; no uniform route deadline | R2b2 native/resource policy; **existing-partial** |
| `shutdown` | Ignored optional mapping | Connected SID; role unrestricted; Global desktop/project/media state | Identity presence only | Close application and exit uvicorn | No response | Application.close | R2b2 native lifecycle policy; **existing-partial** |
| `snooze_reminder` | SnoozeReminder | Authenticated connected owner; role unrestricted; Registry owner; desktop-global reminder list; delivery IDs owner-bound | Shared dispatcher mutation gates | snooze reminder | SID result/error; same-owner refresh | Dispatcher approval deadline; store transaction/lease | ReminderTransport; receipt schema/role policy review remains; **existing** |
| `start_audio` | Legacy optional device mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Heavy-resource gate only; no common direct-action authorization | start audio | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `stop_audio` | Ignored optional mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | stop audio | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `stop_watching` | StopWatching | Authenticated renderer direct; authenticated owner via typed tools; Registry principal and immutable selected-project snapshot | Shared dispatcher per-tool denial/approval; recheck auth/denial after approval | stop watching | SID result/error; stamped bus events to owner renderers | Dispatcher approval deadline; 30s cooperative execution; origin disconnect/app close cancel | LocalActions / LocalActionTransport; **migrated** |
| `take_screenshot` | Screenshot | Authenticated renderer direct; authenticated owner via typed tools; Registry principal and immutable selected-project snapshot | Shared dispatcher per-tool denial/approval; recheck auth/denial after approval | take screenshot | SID result/error; stamped bus events to owner renderers | Dispatcher approval deadline; 30s cooperative execution; origin disconnect/app close cancel | LocalActions / LocalActionTransport; **migrated** |
| `update_settings` | Legacy settings mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | Mutate/persist permissions, face gate and camera settings | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | Next R2b2 authenticated settings/permission transport; **pending** |
| `update_tool_permissions` | Legacy permission mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | Mutate/persist shared permission settings | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | Next R2b2 authenticated settings/permission transport; **pending** |
| `upload_memory` | Legacy memory text mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Legacy route bypass; no common dispatcher | Send untrusted memory context to legacy voice model | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |
| `user_input` | ConversationRequest | Authenticated connected owner; role unrestricted; Registry owner and captured selected project | Shared dispatcher tool gates; durable owner/project request scope | Provider/shared tool work | Result/transcript/error or restore/failure to SID | Existing provider/tool deadlines; durable dedupe; bounded restore | ConversationTransport; role policy review remains; **existing** |
| `video_frame` | Legacy image bytes/base64 mapping | No explicit per-route authentication/role gate; Global desktop/project/media state | Heavy-resource gate only; no common direct-action authorization | video frame | Legacy events/errors may broadcast | Legacy adapter/task; no uniform route deadline | R2b feature transport/policy migration; **pending** |

## HTTP routes

`/status`: local runtime metadata read, no privileged action, immediate HTTP JSON snapshot.

## Shared model tools

These tools use the common dispatcher. Typed ownership is not evidence that a same-named legacy voice declaration has been migrated.

| Tool | Schema | Execution lifetime |
| --- | --- | --- |
| `cancel_reminder` | ReminderAction | Existing provider/service/worker lifetime |
| `control_device` | ControlDevice | 30s cooperative execution |
| `create_reminder` | CreateReminder | Existing provider/service/worker lifetime |
| `generate_cad` | BuildRequest | Existing provider/service/worker lifetime |
| `generate_image` | ImageRequest | Existing provider/service/worker lifetime |
| `get_system_info` | NoArguments | 30s cooperative execution |
| `launch_app` | LaunchApp | 30s cooperative execution |
| `list_all_devices` | NoArguments | 30s cooperative execution |
| `list_reminders` | ListReminders | Existing provider/service/worker lifetime |
| `read_clipboard` | NoArguments | 30s cooperative execution |
| `read_file` | PathArguments | Existing provider/service/worker lifetime |
| `snooze_reminder` | SnoozeReminder | Existing provider/service/worker lifetime |
| `stop_watching` | StopWatching | 30s cooperative execution |
| `take_screenshot` | Screenshot | 30s cooperative execution |
| `write_file` | WriteArguments | Existing provider/service/worker lifetime |

## Legacy voice declarations

All following declarations remain on the separate AudioLoop path, with individual metadata in JSON. Validation/authorization parity remains pending.

| Declaration | Status |
| --- | --- |
| `cancel_reminder` | Legacy voice policy; pending migration |
| `control_device` | Legacy voice policy; pending migration |
| `create_reminder` | Legacy voice policy; pending migration |
| `create_routine` | Legacy voice policy; pending migration |
| `describe_camera` | Legacy voice policy; pending migration |
| `detect_presence` | Legacy voice policy; pending migration |
| `focus_window` | Legacy voice policy; pending migration |
| `generate_cad_prototype` | Legacy voice policy; pending migration |
| `get_device_state` | Legacy voice policy; pending migration |
| `get_system_info` | Legacy voice policy; pending migration |
| `launch_app` | Legacy voice policy; pending migration |
| `list_all_devices` | Legacy voice policy; pending migration |
| `list_reminders` | Legacy voice policy; pending migration |
| `list_routines` | Legacy voice policy; pending migration |
| `list_running_apps` | Legacy voice policy; pending migration |
| `list_watches` | Legacy voice policy; pending migration |
| `read_clipboard` | Legacy voice policy; pending migration |
| `read_directory` | Legacy voice policy; pending migration |
| `read_file` | Legacy voice policy; pending migration |
| `search_files` | Legacy voice policy; pending migration |
| `snooze_reminder` | Legacy voice policy; pending migration |
| `stop_watching` | Legacy voice policy; pending migration |
| `take_screenshot` | Legacy voice policy; pending migration |
| `watch_for` | Legacy voice policy; pending migration |
| `write_clipboard` | Legacy voice policy; pending migration |
| `write_file` | Legacy voice policy; pending migration |

## Remaining sequence

1. **R2b2:** settings/permission mutation and native/resource lifecycle policy, strict schemas and scoped responses. Preserve native receipt and shutdown.
2. **R2b3:** Kasa/printer compatibility, memory, media/legacy creative/browser actions. Printer file containment and slice/upload/start grants need separate validation.
3. Close reminder receipt/role, creative-plan permission, legacy event ownership and voice confirmation gaps. R2c schema/declaration/reference cleanup follows.

Inventory is an observation of current behavior, not an authorization guarantee for pending routes. The local desktop handshake is not a mobile grants protocol. Provider configuration, real-game benchmarking and WhatsApp replies remain excluded.
