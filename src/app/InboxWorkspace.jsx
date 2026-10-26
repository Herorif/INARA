import React, { useEffect, useRef, useState } from "react";
import { RefreshCw, Smartphone } from "lucide-react";
import useStore from "../store";
import socket from "../services/socket";
import { createMobileClient } from "../transport/mobileClient.ts";
import NotificationInbox from "./NotificationInbox";
import PanelState from "./PanelState";
import EmptyState from "../shared/ui/EmptyState";
import StatusChip from "../shared/ui/StatusChip";
import "./mobile-companion.css";
import "./inbox-workspace.css";

function ProjectInbox({ project, connected, locked, onOpen, embedded }) {
  const [report, setReport] = useState(null),
    [error, setError] = useState("");
  const [selected, setSelected] = useState(null),
    [refreshing, setRefreshing] = useState(false);
  const refresh = useRef(null);

  useEffect(() => {
    let live = true,
      inflight = false;
    setReport(null);
    setError("");
    if (!connected || locked) return;
    const client = createMobileClient(socket);
    const read = async () => {
      if (!socket.connected || inflight || !live) return;
      inflight = true;
      setRefreshing(true);
      try {
        const next = await client.state();
        if (live) {
          setReport(next);
          setError("");
        }
      } catch (failure) {
        if (live) {
          setReport(null);
          setError(failure.message);
        }
      } finally {
        inflight = false;
        if (live) setRefreshing(false);
      }
    };
    refresh.current = read;
    const off = client.on("disconnect", () => {
      setReport(null);
      setSelected(null);
    });
    read();
    const timer = setInterval(read, 4000);
    return () => {
      live = false;
      refresh.current = null;
      clearInterval(timer);
      off();
      client.dispose();
    };
  }, [project, connected, locked]);

  // Existing companion identities are the only source of device access.
  // Viewing this surface cannot open a listener, grant access or pair a phone.
  const devices = (connected && !locked ? (report?.devices ?? []) : []).filter(
    (device) => device.project === project && !device.revoked && device.expires > Date.now() / 1000,
  );
  const device = devices.find((item) => item.device_id === selected) ?? devices[0];

  if (locked) return null;
  return (
    <section
      className="inbox-workspace"
      aria-label="Inbox"
    >
      <header className="inbox-workspace-heading">
        <p>Notifications you chose to share from your phone.</p>
        <button className="btn btn--secondary inbox-companion-link" onClick={() => onOpen?.("phone")}>
          <Smartphone size={15} />
          Manage companion
        </button>
      </header>
      <div className="inbox-workspace-body">
        <aside className="inbox-sources" aria-label="Inbox sources">
          <div className="inbox-section-heading">
            <span className="hud-label">Devices</span>
            <button
              className="btn btn--ghost btn--icon btn--sm"
              aria-label="Refresh inbox sources"
              disabled={!connected || refreshing}
              onClick={() => refresh.current?.()}
            >
              <RefreshCw size={15} />
            </button>
          </div>
          {devices.length ? (
            <div className="inbox-device-list">
              {devices.map((item) => (
                <button
                  key={item.device_id}
                  className={item.device_id === device?.device_id ? "is-selected" : ""}
                  aria-pressed={item.device_id === device?.device_id}
                  onClick={() => setSelected(item.device_id)}
                >
                  <Smartphone size={16} aria-hidden="true" />
                  <span>
                    <strong>{item.name}</strong>
                    <small>Paired · {item.project}</small>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="inbox-no-source">
              <StatusChip tone={connected ? "idle" : "danger"}>
                {connected ? "No active source" : "Core offline"}
              </StatusChip>
            </div>
          )}
          <div className="inbox-privacy-note">
            <strong>Privacy</strong>
            <p>
              Only selected notifications enter this project. Permission and retention are managed with your
              companion.
            </p>
          </div>
          <div className="inbox-project">
            <span className="hud-label">Active project</span>
            <strong>{project}</strong>
          </div>
        </aside>
        <div className="inbox-stream-pane">
          {!connected ? (
            <PanelState
              kind="offline"
              title="Core offline"
              detail="Reconnect to the core to view your paired sources and retained notifications."
            />
          ) : error ? (
            <PanelState
              kind="error"
              title="Could not read your sources"
              detail={error}
              action={() => refresh.current?.()}
              actionLabel="Refresh sources"
            />
          ) : !report ? (
            <PanelState
              kind="loading"
              title="Finding your sources"
              detail="Checking paired devices for this project."
            />
          ) : device ? (
            <NotificationInbox
              key={`${project}:${device.device_id}`}
              device={device}
              project={project}
              readOnly
            />
          ) : (
            <EmptyState
              className="inbox-empty"
              title="No paired phone"
              body="Pair your Android phone, then choose which notifications to share with this project. Phone setup and notification permission are separate steps."
              action={
                <button className="btn btn--primary" onClick={() => onOpen?.("phone")}>
                  Open phone companion
                </button>
              }
            />
          )}
          <footer className="inbox-stream-footer">
            <span>Read-only inbox · Replies and AI processing are off</span>
          </footer>
        </div>
      </div>
    </section>
  );
}

export default function InboxWorkspace({ onOpen, embedded = false }) {
  const project = useStore((state) => state.currentProject);
  const connected = useStore((state) => state.backendConnected);
  const locked = useStore((state) => state.isLockScreenVisible);
  // A project switch destroys all pending source reads and notification scopes.
  return (
    <ProjectInbox
      key={project}
      project={project}
      connected={connected}
      locked={locked}
      onOpen={onOpen}
      embedded={embedded}
    />
  );
}
