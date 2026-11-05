import React, { useEffect, useRef, useState } from "react";
import { RefreshCw, Link2, Download } from "lucide-react";
import socket from "../services/socket";
import useStore from "../store";
import { createMobileClient } from "../transport/mobileClient.ts";
import PanelState from "./PanelState";
import StatusChip from "../shared/ui/StatusChip";
import NotificationInbox from "./NotificationInbox";
import "./mobile-companion.css";
export default function MobileCompanion() {
  const project = useStore((s) => s.currentProject),
    connected = useStore((s) => s.backendConnected);
  const [report, setReport] = useState(null),
    [invite, setInvite] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [host, setHost] = useState("127.0.0.1"),
    [chat, setChat] = useState(false),
    [calls, setCalls] = useState(false);
  const client = useRef(null);
  useEffect(() => {
    setCalls(false);
    let live = true,
      inflight = false;
    const value = createMobileClient(socket);
    client.current = value;
    const refresh = async () => {
      if (!socket.connected || inflight) return;
      inflight = true;
      try {
        const next = await value.state();
        if (live) setReport(next);
      } catch (failure) {
        if (live) setError(failure.message);
      } finally {
        inflight = false;
      }
    };
    const off = value.on("disconnect", () => {
      setInvite(null);
      setReport(null);
    });
    setInvite(null);
    setReport(null);
    refresh();
    const timer = setInterval(refresh, 4000);
    const expiry = setInterval(
      () => setInvite((previous) => (previous?.expires <= Date.now() / 1000 ? null : previous)),
      1000,
    );
    return () => {
      live = false;
      clearInterval(timer);
      clearInterval(expiry);
      off();
      if (socket.connected) socket.emit("mobile_pair_cancel", {});
      value.dispose();
    };
  }, [project]);
  const act = async (action) => {
    setBusy(true);
    setError("");
    try {
      const result = await action();
      if (result?.listener) setReport(result);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  };
  const save = () => {
    const blob = new Blob(
        [JSON.stringify(Object.fromEntries(Object.entries(invite).filter(([key]) => key !== "qr_svg")))],
        {
          type: "application/json",
        },
      ),
      url = URL.createObjectURL(blob),
      link = document.createElement("a");
    link.href = url;
    link.download = "jarvis-invitation.jarvis-pair.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const enabled = report?.listener.enabled;
  return (
    <div className="mobile-companion tool-panel">
      <header className="mobile-intro">
        <p>Pair your Android phone with this PC.</p>
      </header>
      {error && <PanelState kind="error" title="Companion action interrupted" detail={error} />}
      <section className="mobile-link-card hud-panel">
        <div className="mobile-card-heading">
          <strong>{enabled ? "Private TLS listener enabled" : "Network access is off"}</strong>
          <StatusChip tone={enabled ? "accent" : "idle"}>{enabled ? "Listening" : "Off"}</StatusChip>
          <button
            className="btn btn--ghost btn--icon btn--sm"
            aria-label="Refresh companion status"
            disabled={!connected || busy}
            onClick={() => act(() => client.current.state())}
          >
            <RefreshCw size={16} />
          </button>
        </div>
        <p className={enabled ? "mobile-mono" : undefined}>
          {enabled
            ? report.listener.endpoint
            : "No mobile port opens until you enable it. Loopback is laptop-only; use your exact private LAN IPv4 address for a phone."}
        </p>
        <label>
          Laptop address
          <input
            className="mobile-mono"
            aria-label="Private laptop IPv4 address"
            value={host}
            disabled={enabled || busy}
            onChange={(event) => setHost(event.target.value)}
          />
        </label>
        <button
          className={`btn ${enabled ? "btn--secondary" : "btn--primary"}`}
          disabled={!connected || busy || !report}
          onClick={() =>
            act(async () => {
              setInvite(null);
              return client.current.listener({
                enabled: !enabled,
                host,
                port: 8443,
              });
            })
          }
        >
          {enabled ? "Stop mobile access" : "Enable private TLS listener"}
        </button>
        <small>
          Port 8443. Listener stays enabled until stopped or the core quits. No firewall or router rules are
          changed.
        </small>
      </section>
      <section className="mobile-link-card hud-panel">
        <div className="mobile-card-heading">
          <strong>Pair with your permission</strong>
        </div>
        <p>
          Read laptop status and job previews in <b>{project}</b>. Compare the full device-key fingerprint on
          both screens before approving.
        </p>
        <label className="mobile-check">
          <input
            type="checkbox"
            checked={chat}
            onChange={(event) => setChat(event.target.checked)}
            disabled={busy}
          />
          Also allow tool-free AI chat for this project
        </label>
        <label className="mobile-check">
          <input
            type="checkbox"
            checked={calls}
            onChange={(event) => setCalls(event.target.checked)}
            disabled={busy}
          />
          Also allow read-only call receipts and caller transcripts for this project
        </label>
        <button
          className={`btn ${enabled ? "btn--primary" : "btn--secondary"}`}
          disabled={!enabled || busy || !connected}
          onClick={() =>
            act(async () =>
              setInvite(
                await client.current.pair({
                  allow_chat: chat,
                  allow_calls: calls,
                }),
              ),
            )
          }
        >
          <Link2 size={16} />
          Create 2-minute invitation
        </button>
        {invite && (
          <div className="mobile-invitation">
            <strong>Invitation ready / {invite.project}</strong>
            {invite.qr_svg ? (
              <img
                className="mobile-qr"
                alt="One-time pairing invitation QR"
                src={`data:image/svg+xml;base64,${invite.qr_svg}`}
              />
            ) : (
              <small>Offline QR rendering is not installed. Invitation-file transfer is available.</small>
            )}
            <p>
              Download and open this file in the Android companion. It expires automatically and can be
              claimed once. Keep it private.
            </p>
            <button className="btn btn--secondary" onClick={save}>
              <Download size={16} />
              Save invitation
            </button>
            <button
              className="btn btn--ghost"
              onClick={() =>
                act(async () => {
                  await client.current.cancel();
                  setInvite(null);
                })
              }
            >
              Cancel invitation
            </button>
          </div>
        )}
      </section>
      {!!report?.pending.length && (
        <section className="mobile-link-card hud-panel">
          <h3>Verify on both screens</h3>
          {report.pending.map((device) => (
            <article key={device.device_id} className="mobile-device">
              <strong>{device.name}</strong>
              <span>
                {device.project} / {device.grants.join(", ")}
              </span>
              <code>{device.fingerprint}</code>
              <div>
                <button
                  className="btn btn--ghost"
                  disabled={busy}
                  onClick={() =>
                    act(() =>
                      client.current.decide({
                        device_id: device.device_id,
                        approved: false,
                      }),
                    )
                  }
                >
                  Decline
                </button>
                <button
                  className="btn btn--secondary"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      setInvite(null);
                      return client.current.decide({
                        device_id: device.device_id,
                        approved: true,
                      });
                    })
                  }
                >
                  Fingerprints match / Approve
                </button>
              </div>
            </article>
          ))}
        </section>
      )}
      <section className="mobile-link-card hud-panel">
        <h3>Paired devices</h3>
        {!report?.devices.length ? (
          <p>No device has access.</p>
        ) : (
          report.devices.map((device) => (
            <article key={device.device_id} className="mobile-device">
              <strong>
                {device.name} /{" "}
                {device.revoked ? "Revoked" : device.expires < Date.now() / 1000 ? "Expired" : "Paired"}
              </strong>
              <span>
                {device.project} / {device.grants.join(", ")}
              </span>
              <code>{device.fingerprint}</code>
              <button
                className="btn btn--danger btn--sm"
                disabled={device.revoked || busy}
                onClick={() =>
                  act(() =>
                    client.current.revoke({
                      device_id: device.device_id,
                    }),
                  )
                }
              >
                Revoke access
              </button>
              {device.project === project && <NotificationInbox device={device} project={project} />}
            </article>
          ))
        )}
      </section>
      <footer>
        Pairing grants only the permissions listed above. Existing devices need a new pairing for call receipt
        access. Calls, notifications, microphone access and WhatsApp replies are not enabled by pairing.
      </footer>
    </div>
  );
}
