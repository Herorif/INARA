import React, { useEffect, useRef, useState } from "react";
import { ShieldCheck, RefreshCw } from "lucide-react";
import useStore from "../store";
import socket from "../services/socket";
import { createUsageClient, parseAllowance } from "../transport/usageClient.ts";
import PanelState from "./PanelState";
import StatusChip from "../shared/ui/StatusChip";
import "./usage-center.css";
const receiptTone = (state) =>
  /complete|settled|success/.test(state)
    ? "ok"
    : /fail|error|denied|blocked/.test(state)
      ? "danger"
      : /reserved|running|active/.test(state)
        ? "accent"
        : /uncertain|cancel|timeout|unknown/.test(state)
          ? "warn"
          : "idle";
const share = (value, max) => `${Math.min(100, Math.max(0, (value / Math.max(1, max)) * 100))}%`;
const money = (value) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 6 }).format(
    value / 1000000,
  );
export default function UsageCenter() {
  const project = useStore((s) => s.currentProject),
    connected = useStore((s) => s.backendConnected);
  const [report, setReport] = useState(null),
    [quality, setQuality] = useState({ report: null, running: false }),
    [form, setForm] = useState(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [running, setRunning] = useState(false);
  const client = useRef(null),
    refresh = useRef(() => {}),
    generation = useRef(0);
  useEffect(() => {
    const value = createUsageClient(socket, project);
    client.current = value;
    const epoch = ++generation.current;
    setReport(null);
    setForm(null);
    setQuality({ report: null, running: false });
    setError("");
    setNotice("");
    setRunning(false);
    refresh.current = async () => {
      setBusy(true);
      try {
        const [usage, next] = await Promise.all([value.state(), value.quality()]);
        if (generation.current === epoch) {
          setReport(usage);
          setQuality(next);
          setError("");
        }
      } catch (failure) {
        if (generation.current === epoch) setError(failure.message);
      } finally {
        if (generation.current === epoch) setBusy(false);
      }
    };
    const off = value.on("disconnect", () => {
      setReport(null);
      setForm(null);
      setQuality({ report: null, running: false });
      setBusy(false);
      setRunning(false);
      setError("Disconnected. Reconnect and review; actions are never replayed.");
    });
    const reconnect = value.on("connect", () => refresh.current());
    if (socket.connected) refresh.current();
    return () => {
      // eslint-disable-next-line react-hooks/exhaustive-deps -- a request counter, not a DOM ref: bumping its live value invalidates in-flight replies
      generation.current++;
      off();
      reconnect();
      if (socket.connected) socket.emit("quality_cancel", {});
      value.dispose();
    };
  }, [project]);
  const act = async (action, done) => {
    const epoch = generation.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next = await action();
      if (generation.current === epoch) done?.(next);
    } catch (failure) {
      if (generation.current === epoch) setError(failure.message);
    } finally {
      if (generation.current === epoch) setBusy(false);
    }
  };
  const edit = () => {
    const p = report.policy;
    setForm({
      revision: p.revision,
      enabled: p.enabled,
      daily: String(p.daily_microusd / 1000000),
      monthly: String(p.monthly_microusd / 1000000),
      perCall: String(p.per_call_microusd / 1000000),
      tokens: p.max_output_tokens,
    });
  };
  const field = (key, value) => setForm((previous) => ({ ...previous, [key]: value }));
  const save = (event) => {
    event.preventDefault();
    act(
      () =>
        client.current.configure({
          revision: form.revision,
          enabled: form.enabled,
          daily_microusd: parseAllowance(form.daily),
          monthly_microusd: parseAllowance(form.monthly),
          per_call_microusd: parseAllowance(form.perCall),
          max_output_tokens: Number(form.tokens),
        }),
      (next) => {
        setReport(next);
        setForm(null);
        setNotice("Budget policy saved. Existing usage and in-flight allowances were retained.");
      },
    );
  };
  const run = () => {
    const epoch = generation.current;
    setRunning(true);
    act(
      () => client.current.run(),
      (next) => setQuality(next),
    ).finally(() => {
      if (generation.current === epoch) setRunning(false);
    });
  };
  const q = quality.report;
  return (
    <div className="usage-center tool-panel">
      <header className="usage-intro">
        <p>Cloud usage, allowances and receipts.</p>
      </header>
      <div className="usage-toolbar">
        <button
          className="btn btn--primary"
          disabled={!report || busy || running || !connected}
          onClick={edit}
        >
          <ShieldCheck size={15} />
          Review budget
        </button>
        <button
          className="btn btn--secondary"
          disabled={!connected || busy || running}
          onClick={() => refresh.current()}
        >
          <RefreshCw size={15} />
          Refresh
        </button>
        <StatusChip
          tone={report?.policy.enabled ? "ok" : "idle"}
          className={`usage-mode ${report?.policy.enabled ? "capped" : ""}`}
        >
          {report?.policy.enabled ? "CAPS ENABLED" : "MONITOR ONLY"}
        </StatusChip>
      </div>
      {error && <PanelState kind="error" title="Usage action interrupted" detail={error} />}
      {notice && (
        <p className="usage-notice" role="status">
          {notice}
        </p>
      )}
      {report && (
        <>
          <section className="usage-meters">
            <article className="hud-panel">
              <span className="hud-label">Authorized today / UTC</span>
              <strong className="tnum">{money(report.daily_authorized_microusd)}</strong>
              <small className="tnum">
                {report.policy.enabled
                  ? `Limit ${money(report.policy.daily_microusd)}`
                  : "Caps off / no allowance charged"}
              </small>
              <span
                className="usage-bar"
                role="progressbar"
                aria-label="Daily allowance used"
                aria-valuemin={0}
                aria-valuemax={Math.max(1, report.policy.daily_microusd)}
                aria-valuenow={Math.min(report.daily_authorized_microusd, report.policy.daily_microusd)}
              >
                <span style={{ width: share(report.daily_authorized_microusd, report.policy.daily_microusd) }} />
              </span>
            </article>
            <article className="hud-panel">
              <span className="hud-label">Authorized this month / UTC</span>
              <strong className="tnum">{money(report.monthly_authorized_microusd)}</strong>
              <small className="tnum">
                {report.policy.enabled
                  ? `Limit ${money(report.policy.monthly_microusd)}`
                  : "Caps off / no allowance charged"}
              </small>
              <span
                className="usage-bar"
                role="progressbar"
                aria-label="Monthly allowance used"
                aria-valuemin={0}
                aria-valuemax={Math.max(1, report.policy.monthly_microusd)}
                aria-valuenow={Math.min(report.monthly_authorized_microusd, report.policy.monthly_microusd)}
              >
                <span
                  style={{ width: share(report.monthly_authorized_microusd, report.policy.monthly_microusd) }}
                />
              </span>
            </article>
            <article className="hud-panel">
              <span className="hud-label">Metered cloud calls / month</span>
              <strong className="tnum">{report.cloud_calls_this_month}</strong>
              <small className="tnum">
                {report.day_utc} / {report.month_utc}
              </small>
            </article>
          </section>
          <p className="usage-scope">
            Limits are shared across your projects, desktop/speech and paired-phone chat. Receipts below show{" "}
            <b>{project}</b>. Metered paths cover chat, CAD proposals and transcription. Provider invoice cost
            is unknown; these totals are INARA authorization allowances.
          </p>
          {form && (
            <form className="usage-policy" onSubmit={save}>
              <h3>Review cloud authorization</h3>
              <label className="usage-check">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(event) => field("enabled", event.target.checked)}
                />
                Enforce daily/monthly admission limits
              </label>
              <div className="usage-policy-grid">
                <label>
                  Daily allowance (USD)
                  <input
                    aria-label="Daily authorization allowance"
                    inputMode="decimal"
                    value={form.daily}
                    onChange={(event) => field("daily", event.target.value)}
                  />
                </label>
                <label>
                  Monthly allowance (USD)
                  <input
                    aria-label="Monthly authorization allowance"
                    inputMode="decimal"
                    value={form.monthly}
                    onChange={(event) => field("monthly", event.target.value)}
                  />
                </label>
                <label>
                  Reserve per cloud call (USD)
                  <input
                    aria-label="Per call authorization allowance"
                    inputMode="decimal"
                    value={form.perCall}
                    onChange={(event) => field("perCall", event.target.value)}
                  />
                </label>
                <label>
                  Maximum output tokens per capped call
                  <input
                    aria-label="Maximum output tokens"
                    type="number"
                    min="256"
                    max="16384"
                    value={form.tokens}
                    onChange={(event) => field("tokens", event.target.value)}
                  />
                </label>
              </div>
              <p>
                A positive per-call allowance is required when enabled. A zero daily/monthly limit pauses new
                cloud calls. Every tool-loop provider step reserves separately. Timeouts, cancellations and
                missing usage metadata retain the allowance; no automatic refunds or retries occur.
              </p>
              <p>
                Allowances are owner-chosen controls, not provider pricing or guaranteed invoice ceilings. Set
                provider-side billing controls separately. Enabling caps blocks legacy cloud
                browser/vision/generated-code adapters that cannot yet be metered. Existing legacy tasks must
                stop before enabling this policy. Local CAD and image jobs remain local and use the existing
                resource admission rules.
              </p>
              <div className="usage-toolbar">
                <button className="btn btn--secondary" disabled={busy || !connected} type="submit">
                  Apply reviewed budget
                </button>
                <button className="btn btn--ghost" type="button" disabled={busy} onClick={() => setForm(null)}>
                  Cancel edit
                </button>
              </div>
            </form>
          )}
          <section className="quality-card hud-panel">
            <div className="quality-heading">
              <div>
                <span className="hud-label">Offline contract evaluations</span>
                <h3 className="tnum">
                  {q ? `${q.passed_count} / ${q.total} checks passed` : "Offline checks not run yet"}
                </h3>
              </div>
              <StatusChip className="quality-fixture">Fixtures only</StatusChip>
            </div>
            <p>
              Synthetic assistant, memory, budget, CAD and image checks run in an isolated disposable profile
              with network access blocked. These verify contracts and artifacts; real model creativity,
              accuracy and provider latency remain unverified.
            </p>
            <div className="usage-toolbar">
              <button
                className="btn btn--secondary"
                disabled={!connected || busy || running || quality.running}
                onClick={run}
              >
                {running ? "Running offline checks" : "Run offline checks"}
              </button>
              {(running || quality.running) && (
                <button
                  className="btn btn--ghost"
                  disabled={!connected}
                  onClick={() =>
                    act(
                      () => client.current.cancel(),
                      (next) => setQuality(next),
                    )
                  }
                >
                  Stop checks
                </button>
              )}
            </div>
            {q && (
              <>
                <small>
                  Suite <span className="usage-mono">{q.suite_version}</span> /{" "}
                  <span className="usage-mono tnum">{q.duration_seconds}s</span> / no paid provider / no real
                  user data
                </small>
                <ol className="quality-cases">
                  {q.cases.map((item) => (
                    <li key={item.id}>
                      <StatusChip
                        tone={item.passed ? "ok" : "danger"}
                        className={item.passed ? "quality-pass" : "quality-fail"}
                      >
                        {item.passed ? "PASS" : "FAIL"}
                      </StatusChip>
                      <strong>{item.id.replaceAll("_", " ")}</strong>
                      <time className="tnum">{item.duration_seconds}s</time>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </section>
          <section className="usage-history">
            <div className="usage-section-heading">
              <h3>Request & job receipts</h3>
              <span>{project} / latest 50 this month</span>
            </div>
            {!report.records.length ? (
              <p>No receipts yet. Local jobs and metered cloud calls appear after they run.</p>
            ) : (
              <ol>
                {report.records.map((row) => (
                  <li key={row.id}>
                    <div className="usage-receipt-heading">
                      <strong>{row.feature.replaceAll("_", " ")}</strong>
                      <StatusChip tone={receiptTone(row.state)}>{row.state}</StatusChip>
                    </div>
                    <small className="usage-reference">
                      {row.request_id ? `Request ${row.request_id}` : `Receipt ${row.id.slice(0, 12)}`}
                      {row.provider_step != null ? ` / provider step ${row.provider_step + 1}` : ""}
                    </small>
                    <div className="usage-receipt-meta">
                      <span className="usage-mono">{row.model}</span>
                      <time className="usage-mono tnum">{new Date(row.created_at * 1000).toLocaleString()}</time>
                      <span className="usage-mono tnum">
                        {row.duration_seconds == null
                          ? "In progress / duration unknown"
                          : `${row.duration_seconds}s`}
                      </span>
                      <b className="tnum">
                        {row.cloud
                          ? `Allowance ${money(row.allowance_microusd)}`
                          : "Local worker / no cloud allowance"}
                      </b>
                    </div>
                    {row.cloud && (
                      <details>
                        <summary>
                          {row.tokens
                            ? `Reported tokens: ${row.tokens.total_tokens ?? "total unavailable"}`
                            : "Provider token usage unavailable"}
                        </summary>
                        {row.tokens ? (
                          <div className="usage-token-grid">
                            {Object.entries(row.tokens).map(([key, value]) => (
                              <span key={key}>
                                {key.replaceAll("_", " ")}
                                <b className="tnum">{value}</b>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <p>Missing metadata is unknown usage. Any reserved allowance remains consumed.</p>
                        )}
                      </details>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </div>
  );
}
