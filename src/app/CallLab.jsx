import React, { useEffect, useRef, useState } from "react";
import { RefreshCw, Square } from "lucide-react";
import useStore from "../store";
import socket from "../services/socket";
import { createCallLabClient } from "../transport/callLabClient.ts";
import PanelState from "./PanelState";
import StatusChip from "../shared/ui/StatusChip";
import EmptyState from "../shared/ui/EmptyState";
import ControlledCallTest from "./ControlledCallTest";
import "./call-lab.css";

const runTone = { completed: "ok", running: "accent", uncertain: "warn", failed: "danger" };

export default function CallLab() {
  const project = useStore((state) => state.currentProject);
  const connected = useStore((state) => state.backendConnected);
  const [report, setReport] = useState(null),
    [record, setRecord] = useState(null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const client = useRef(null),
    epoch = useRef(0),
    active = useRef(null),
    refresh = useRef(() => {});
  const readVersion = useRef(0),
    mutating = useRef(false);
  useEffect(() => {
    const generation = ++epoch.current,
      api = createCallLabClient(socket, project);
    mutating.current = false;
    readVersion.current++;
    client.current = api;
    active.current = null;
    setReport(null);
    setRecord(null);
    setError("");
    setBusy(false);
    let reading = false;
    refresh.current = async () => {
      if (reading || mutating.current || !socket.connected) return;
      reading = true;
      const version = ++readVersion.current;
      try {
        const next = await api.state();
        if (epoch.current === generation && version === readVersion.current) {
          setReport(next);
          active.current = next.runs.find((item) => item.state === "running")?.id || null;
        }
      } catch (failure) {
        if (epoch.current === generation && version === readVersion.current) {
          setError(failure.message);
          setReport(null);
          setRecord(null);
        }
      } finally {
        reading = false;
      }
    };
    refresh.current();
    const timer = setInterval(() => {
      if (!document.hidden) refresh.current();
    }, 1000);
    return () => {
      epoch.current++;
      clearInterval(timer);
      if (active.current && socket.connected) api.stop(active.current).catch(() => {});
      active.current = null;
      api.dispose();
    };
  }, [project, connected]);
  const act = async (operation) => {
    const generation = epoch.current;
    readVersion.current++;
    mutating.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await operation();
      if (epoch.current !== generation) return;
      if (next.runs) {
        setReport(next);
        active.current = next.runs.find((item) => item.state === "running")?.id || null;
      } else setRecord(next);
    } catch (failure) {
      if (epoch.current === generation) setError(failure.message);
    } finally {
      if (epoch.current === generation) {
        readVersion.current++;
        mutating.current = false;
        setBusy(false);
      }
    }
  };
  const running = report?.runs.find((item) => item.state === "running");
  return (
    <div className="call-lab tool-panel">
      <header className="call-lab__hero">
        <div className="call-lab__hero-copy">
          <p>Test the local call bridge safely.</p>
        </div>
        <StatusChip className="call-lab__badge">Unattended answering off / controlled tests gated</StatusChip>
      </header>
      <div className="call-lab__routes">
        <article className="hud-panel">
          <div className="call-lab__route-top">
            <h3>SIM via Phone Link</h3>
            <StatusChip tone="warn">Unverified</StatusChip>
          </div>
          <p>
            Windows Bluetooth is the candidate route. Phone pairing, call controls and isolated audio still
            need a real-device test.
          </p>
        </article>
        <article className="hud-panel">
          <div className="call-lab__route-top">
            <h3>Personal WhatsApp</h3>
            <StatusChip tone="warn">Unverified</StatusChip>
          </div>
          <p>
            The official Windows client is the candidate bridge. Automatic answering is experimental and
            remains unverified.
          </p>
        </article>
      </div>
      <section className="call-lab__readiness hud-panel" aria-label="Call bridge readiness">
        <header>
          <h3>Local readiness</h3>
          <button
            className="btn btn--ghost btn--icon btn--sm"
            disabled={!connected || busy}
            onClick={() => {
              setError("");
              refresh.current();
            }}
            aria-label="Refresh call bridge readiness"
          >
            <RefreshCw size={15} />
          </button>
        </header>
        <dl>
          {[
            ["Native control helper", report?.helper_built],
            ["Dedicated audio adapter", report?.audio_installed],
            ["Local English speech components", report?.voice_configured],
          ].map(([label, ready]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>
                <StatusChip tone={ready == null ? "idle" : ready ? "accent" : "warn"}>
                  {ready == null ? "Unknown" : ready ? "Present / unverified" : "Setup needed"}
                </StatusChip>
              </dd>
            </div>
          ))}
        </dl>
        <dl>
          <div>
            <dt>Shared session admission</dt>
            <dd>
              {!report
                ? "Unknown"
                : report.admission.admission_ready
                  ? "Software ready / device test pending"
                  : "Not ready"}
            </dd>
          </div>
          <div>
            <dt>Optional conversational model</dt>
            <dd>
              {!report
                ? "Unknown"
                : report.model_accepted
                  ? "Local evaluation passed"
                  : report.model_installed
                    ? "Installed / evaluation needed"
                    : "Not installed"}
            </dd>
          </div>
          <div>
            <dt>Speech processing</dt>
            <dd>Local only / no cloud fallback</dd>
          </div>
        </dl>
        {report && (
          <p role="status">
            {report.admission.blockers
              .map(
                (code) =>
                  ({
                    call_components_missing: "Local components need setup",
                    call_resources_busy: "Another worker owns the resources",
                    resource_policy: "Leave resident or gaming mode",
                    resource_fault: "Resource checks need attention",
                    resource_capacity: "Not enough available capacity",
                    call_physical_unverified: "Controlled phone and audio acceptance pending",
                  })[code],
              )
              .join(" · ")}
            .
          </p>
        )}
        <p>Presence is not proof of live calling. This panel opens no phone app, microphone or provider.</p>
      </section>
      <ControlledCallTest project={project} connected={connected} />
      {error && <PanelState compact kind="error" title="Bridge check interrupted" detail={error} />}
      <section className="call-lab__check hud-panel">
        <div>
          <h3>Isolated bridge check</h3>
          <p>
            A disposable worker exercises the call lifecycle using synthetic controls, audio and speech. It
            saves a labeled test transcript, then exits.
          </p>
        </div>
        <div className="call-lab__actions">
          <button
            className="btn btn--primary primary-button"
            disabled={!connected || busy || !report?.worker_supported || report?.worker_busy}
            onClick={() => {
              const id = crypto.randomUUID();
              active.current = id;
              setRecord(null);
              return act(() => client.current.check(id));
            }}
          >
            Run isolated bridge check
          </button>
          {running && (
            <button
              className="btn btn--danger"
              disabled={busy || !connected}
              onClick={() => act(() => client.current.stop(running.id))}
            >
              <Square size={14} />
              Stop check
            </button>
          )}
        </div>
        {running && (
          <p className="call-lab__progress" role="status">
            <span className="status-dot status-dot--accent call-lab__live" aria-hidden="true" />
            Simulation running · No live call
          </p>
        )}
      </section>
      <section className="call-lab__history">
        <h3>Bridge check history</h3>
        <p>These are software diagnostics, not a history of real callers.</p>
        {!report?.runs.length && (
          <EmptyState
            className="call-lab__empty"
            title="No checks yet"
            body="Run a local check to inspect the supervised lifecycle. Real call acceptance is a separate step."
          />
        )}
        {report?.runs.map((item) => (
          <article key={item.id}>
            <div>
              <strong>Offline simulation</strong>
              <small className="call-lab__mono tnum">{new Date(item.started_at * 1000).toLocaleString()}</small>
            </div>
            <StatusChip tone={runTone[item.state] || "idle"} className={`call-lab__state is-${item.state}`}>
              {item.state}
            </StatusChip>
            {item.record_id && item.state !== "running" && (
              <button
                className="btn btn--secondary btn--sm"
                disabled={busy || !connected}
                onClick={() => act(() => client.current.record(item.id, item.record_id))}
              >
                Review test record
              </button>
            )}
            {item.code && (
              <small className="call-lab__code call-lab__mono">{item.code.replaceAll("_", " ")}</small>
            )}
          </article>
        ))}
      </section>
      {record && (
        <section className="call-lab__transcript hud-panel" aria-label="Synthetic call transcript">
          <header>
            <div>
              <span className="hud-label">Synthetic / local record</span>
              <h3>Test transcript</h3>
            </div>
            <button className="btn btn--ghost btn--sm" onClick={() => setRecord(null)}>
              Close record
            </button>
          </header>
          {record.transcript.map((item, index) => (
            <div className={`call-lab__segment is-${item.role}`} key={index}>
              <strong>{item.role === "caller" ? "Simulated caller" : "Simulated INARA"}</strong>
              <p>{item.text}</p>
            </div>
          ))}
          {!record.transcript.length && <p>No transcript was captured before this check stopped.</p>}
        </section>
      )}
      <footer>
        <p>
          Checks stay with this owner and project. Closing the panel, disconnecting, locking, changing project
          or entering gaming mode stops its worker. Personal WhatsApp text replies stay off.
        </p>
      </footer>
    </div>
  );
}
