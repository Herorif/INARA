# Home Assistant

JARVIS can see and control the lights, switches, fans, climate, media players, locks,
covers, alarms, scenes and scripts in your Home Assistant. You choose, device by device,
what JARVIS may do on its own.

## Setup

1. In Home Assistant, open your profile.
2. Open the Security tab.
3. Under **Long-lived access tokens**, select **Create token** and name it JARVIS.
4. Copy the token. Home Assistant shows it only once.
5. In JARVIS, open **Connections**. Under **Accounts**, find the **Home Assistant** card.
6. Enter the **Server address**, for example `http://homeassistant.local:8123`, paste the
   **Long-lived access token** and press **Connect**.

Connect checks that the address answers `GET /api/` with "API running." and reads your
devices. When it works, the card shows "Connected to <host> · N devices in M rooms".
Disconnect deletes the token from this PC and keeps the address for next time.

### Addresses

- `https://` addresses are checked against the Windows certificate store, so a certificate
  from your own authority or an antivirus that scans HTTPS still works. A self-signed
  certificate that Windows doesn't trust is refused ("couldn't make a secure connection").
- `http://` is accepted only for addresses on your home network: private IP addresses
  (192.168.x.x, 10.x.x.x, 172.16-31.x.x), link-local and loopback addresses, the
  100.64.0.0/10 range (Tailscale), names without a dot and names ending in `.local`, `.lan`,
  `.home`, `.home.arpa`, `.internal` or `.localdomain`. The card notes that such an address
  isn't encrypted. Use https for anything reachable from outside your home.
- Leave out `/api`, a sign-in name and anything after `?`.

### Errors on the card

| What you see | What it means |
| --- | --- |
| Home Assistant didn't accept this token | 401 or 403: the token is wrong, revoked or for another server. |
| JARVIS couldn't reach Home Assistant at this address | Nothing answered: check the address and that this PC is on your home network. |
| Home Assistant didn't answer within 10 seconds | Every request has a 10 second limit. |
| JARVIS couldn't make a secure connection | The https certificate isn't trusted for this address. |
| This address doesn't look like Home Assistant | The address answered, but not as Home Assistant's API (check the port, usually 8123). |

## Rooms and devices

**Home** (the window that used to be the Kasa smart-home window; its command and route are
unchanged) shows your devices grouped by Home Assistant **area**. JARVIS reads the areas by
rendering a template through `POST /api/template`. If that fails, for example on an older
Home Assistant, devices are grouped by kind (Lights, Switches, Locks and so on) instead.
Devices without an area are under **Other**. Kasa devices stay in their own **Kasa** group
and work as before.

Each tile shows the device's state, a switch where it can be switched, a brightness bar
for dimmable lights that are on, the set point and mode for climate, and JARVIS's access.
Your own clicks on a tile act at once: you are the owner, so there is no approval card.
**Refresh** reads the devices again; states don't update live.

## JARVIS access per device

Choose from the tile menu:

| Access | What JARVIS does |
| --- | --- |
| **JARVIS can control** | Acts when you ask, without asking again. |
| **Always asks** | Shows an approval card such as "Unlock Front door?" with **Unlock** and **Not now**, and acts only if you approve. |
| **Off limits** | Can't control the device, and sees only its name and room. Only you can set this. |

Defaults: lights, switches, input booleans, fans, media players, climate and scenes are
**JARVIS can control**; locks, covers, alarm panels and scripts are **Always asks**. Nothing
is off limits until you choose it.

Some actions **always ask**, whatever you chose, unless the device is off limits:
unlocking a lock, opening a cover, and arming or disarming an alarm. You can't make them
silent.

Only your changes are saved (`home_assistant.access` in settings): a device set back to its
default has no entry.

## For the brain

- `home_devices {room?, domain?}` lists devices with their room, state and access. It
  never asks. Off limits devices appear by name and room only, with no entity ID, state or
  actions.
- `home_control {entity_id, action, value?}` acts on one device. Actions: `turn_on`,
  `turn_off`, `toggle`, `set_brightness` (0-100), `set_temperature`, `activate` (scene or
  script), `lock`, `unlock`, `open`, `close`, `arm_home`, `arm_away`, `disarm`,
  `media_play`, `media_pause` and `volume` (0-100). Off limits devices and actions a device
  can't do are refused before any card.

Both tool permissions default to "never ask" (`home_devices` and `home_control` set to
`false`); the per-device asking above comes from `ToolSpec.ask_when` in the dispatcher.
Setting either permission to "deny" in Preferences turns the tool off.

## Privacy and storage

- The token is stored encrypted on this PC (Windows DPAPI) as the secret
  `home_assistant_token`. It is saved only by Connect after Home Assistant accepted it, is
  never sent back to the screen and is never written to a log. A developer can override it
  with the `JARVIS_HOME_ASSISTANT_TOKEN` environment variable.
- The address is the setting `home_assistant.url`.
- Older versions read a `home_assistant.token` from settings.json. That token is now
  ignored, and the card says so once with "An old token in settings was ignored; paste it
  again here to store it encrypted". Connect or Disconnect removes it from settings.json.
- JARVIS's log records only error codes, device kinds and actions, never the token, the
  address or device names.
- Device names come from your Home Assistant. The brain is told to treat them as data,
  never as instructions.
- All requests go from this PC straight to your Home Assistant, with redirects off.

## Owner-only routes

`home_status`, `home_connect {url, token}`, `home_disconnect`, `home_devices`,
`home_set_access {entity_id, access}` and `home_control_direct {entity_id, action, value?}`
need the unlocked owner's JARVIS window. The core pushes `home_status` to it when the
connection or the device count changes. See docs/ROUTE_POLICY_MATRIX.json.
