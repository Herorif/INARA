import React, { useEffect, useRef, useState } from "react";
import { Plus, Square, RefreshCw, Trash2, ShieldCheck } from "lucide-react";
import useStore from "../store";
import socket from "../services/socket";
import { createTaskQueueClient } from "../transport/taskQueueClient.ts";
import StatusChip from "../shared/ui/StatusChip";
import EmptyState from "../shared/ui/EmptyState";
import "./task-queue.css";
const tone = {
  completed: "ok",
  running: "accent",
  awaiting_approval: "accent",
  uncertain: "warn",
  interrupted: "warn",
  failed: "danger",
};
const initialStep = () => ({ tool: "write_file", path: "notes/plan.txt", content: "" });
const label = {
  read_file: "Read project file",
  write_file: "Write project file",
  launch_app: "Open registered app",
};
export default function TaskQueue() {
  const project = useStore((s) => s.currentProject),
    connected = useStore((s) => s.backendConnected);
  const [data, setData] = useState(null),
    [title, setTitle] = useState("Project preparation"),
    [steps, setSteps] = useState([initialStep()]),
    [selected, setSelected] = useState(null),
    [busy, setBusy] = useState(false),
    [running, setRunning] = useState(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const client = useRef(null),
    generation = useRef(0),
    runId = useRef(null),
    draftId = useRef(crypto.randomUUID());
  useEffect(() => {
    const epoch = ++generation.current,
      c = createTaskQueueClient(socket, project);
    client.current = c;
    runId.current = null;
    draftId.current = crypto.randomUUID();
    setData(null);
    setSelected(null);
    setRunning(null);
    setBusy(false);
    setError("");
    setNotice("");
    setTitle("Project preparation");
    setSteps([initialStep()]);
    if (connected)
      c.state()
        .then((value) => {
          if (generation.current === epoch) setData(value);
        })
        .catch((failure) => {
          if (generation.current === epoch) setError(failure.message);
        });
    return () => {
      // eslint-disable-next-line react-hooks/exhaustive-deps -- a request counter, not a DOM ref: bumping its live value invalidates in-flight replies
      generation.current++;
      if (socket.connected && runId.current) c.cancel(runId.current).catch(() => {});
      c.dispose();
      if (useStore.getState().confirmationRequest?.task_queue)
        useStore.setState({ confirmationRequest: null });
    };
  }, [project, connected]);
  const active = !!running || data?.tasks.some((task) => task.state === "running");
  useEffect(() => {
    if (!active || !connected) return;
    const epoch = generation.current;
    let pending = false;
    const timer = setInterval(async () => {
      if (pending) return;
      pending = true;
      try {
        const value = await client.current.state();
        if (generation.current === epoch) setData(value);
      } catch (failure) {
        if (generation.current === epoch) setError(failure.message);
      } finally {
        pending = false;
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [active, connected]);
  const act = async (action) => {
    const epoch = generation.current;
    setBusy(true);
    setError("");
    try {
      const value = await action();
      if (generation.current === epoch) setData(value);
      return generation.current === epoch ? value : undefined;
    } catch (failure) {
      if (generation.current === epoch) setError(failure.message);
    } finally {
      if (generation.current === epoch) setBusy(false);
    }
  };
  const save = async (event) => {
    event.preventDefault();
    const id = draftId.current;
    const value = await act(() => client.current.create({ id, title, steps }));
    if (value) {
      setSelected(id);
      draftId.current = crypto.randomUUID();
      setNotice("Plan saved for review. No steps have run.");
    }
  };
  const run = async (task) => {
    if (runId.current) return;
    const epoch = generation.current;
    runId.current = task.id;
    setRunning(task.id);
    setError("");
    setNotice("Review each permission request. You can stop before the next step.");
    try {
      const value = await client.current.run(task.id);
      if (generation.current === epoch) {
        setData(value);
        setNotice("Task attempt finished. Review the step receipts below.");
      }
    } catch (failure) {
      if (generation.current === epoch) {
        setError(failure.message);
        try {
          const value = await client.current.state();
          if (generation.current === epoch) setData(value);
        } catch {
          // Best-effort resync; the original failure is already shown.
        }
      }
    } finally {
      if (generation.current === epoch) {
        runId.current = null;
        setRunning(null);
      }
    }
  };
  const change = (index, values) =>
    setSteps((previous) => previous.map((step, i) => (i === index ? { ...step, ...values } : step)));
  const choose = (index, tool) =>
    setSteps((previous) =>
      previous.map((step, i) =>
        i !== index
          ? step
          : tool === "launch_app"
            ? { tool, name: "notepad" }
            : tool === "read_file"
              ? { tool, path: "notes/plan.txt" }
              : initialStep(),
      ),
    );
  const task = data?.tasks.find((item) => item.id === selected);
  return (
    <section className="task-queue" aria-label="Reviewed task queue">
      <header className="task-queue__header">
        <p>Review and run multi-step desktop tasks.</p>
        <StatusChip tone={active ? "accent" : "idle"} className="task-queue__badge">
          {active ? "Task active" : "Idle"}
        </StatusChip>
      </header>
      <div className="task-queue__policy">
        <ShieldCheck size={16} aria-hidden="true" />
        <span>Every step needs approval. Interrupted actions never resume automatically.</span>
      </div>
      {error && (
        <p className="task-queue__error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="task-queue__notice" role="status">
          {notice}
        </p>
      )}
      <div className="task-queue__layout">
        <form className="task-queue__composer" onSubmit={save}>
          <div className="task-queue__section">
            <h3>Build a plan</h3>
            <span className="hud-label">Up to 8 steps</span>
          </div>
          <label className="task-queue__field">
            Plan name
            <input
              aria-label="Task plan name"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={100}
              required
              disabled={busy || active}
            />
          </label>
          <ol className="task-queue__steps">
            {steps.map((step, index) => (
              <li key={index}>
                <div className="task-queue__step-top">
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <select
                    aria-label={`Step ${index + 1} operation`}
                    value={step.tool}
                    onChange={(e) => choose(index, e.target.value)}
                    disabled={busy || active}
                  >
                    {Object.entries(label).map(([value, text]) => (
                      <option key={value} value={value}>
                        {text}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn--ghost btn--icon btn--sm task-queue__icon"
                    aria-label={`Remove step ${index + 1}`}
                    onClick={() => setSteps((previous) => previous.filter((_, i) => i !== index))}
                    disabled={steps.length === 1 || busy || active}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                {step.tool === "launch_app" ? (
                  <label className="task-queue__field">
                    Registered app
                    <select
                      aria-label={`Step ${index + 1} app`}
                      value={step.name}
                      onChange={(e) => change(index, { name: e.target.value })}
                      disabled={busy || active}
                    >
                      {["notepad", "calculator", "paint", "explorer", "vscode"].map((name) => (
                        <option key={name}>{name}</option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <label className="task-queue__field">
                    Path inside this project
                    <input
                      aria-label={`Step ${index + 1} path`}
                      value={step.path}
                      onChange={(e) => change(index, { path: e.target.value })}
                      maxLength={1024}
                      required
                      disabled={busy || active}
                    />
                  </label>
                )}
                {step.tool === "write_file" && (
                  <label className="task-queue__field">
                    File content
                    <textarea
                      aria-label={`Step ${index + 1} content`}
                      value={step.content}
                      onChange={(e) => change(index, { content: e.target.value })}
                      maxLength={16000}
                      rows={4}
                      disabled={busy || active}
                    />
                    <small>
                      Writing replaces the selected file. Review the path and content before approving.
                    </small>
                  </label>
                )}
              </li>
            ))}
          </ol>
          <div className="task-queue__actions">
            <button
              type="button"
              className="btn btn--secondary task-queue__secondary"
              onClick={() => setSteps((previous) => [...previous, initialStep()])}
              disabled={steps.length >= 8 || busy || active}
            >
              <Plus size={15} /> Add step
            </button>
            <button className="btn btn--primary" type="submit" disabled={busy || active || !connected}>
              Save for review
            </button>
          </div>
          <p className="task-queue__hint">
            Plans are immutable after saving. No scripts, website actions, AI planning or result-to-command
            substitution. Closing this panel stops its active task; completed effects are not undone.
          </p>
        </form>
        <div className="task-queue__review">
          <div className="task-queue__section">
            <h3>Plans & receipts</h3>
            <button
              type="button"
              className="btn btn--ghost btn--icon btn--sm task-queue__icon"
              aria-label="Refresh task receipts"
              onClick={() => act(() => client.current.state())}
              disabled={busy || !connected}
            >
              <RefreshCw size={15} />
            </button>
          </div>
          {!data ? (
            <p className="task-queue__hint">
              {connected ? "Loading protected project receipts..." : "Connect to the core to review tasks."}
            </p>
          ) : (
            <>
              <div className="task-queue__list">
                {data.tasks.length ? (
                  data.tasks.map((item) => (
                    <button
                      type="button"
                      className={selected === item.id ? "is-selected" : ""}
                      key={item.id}
                      onClick={() => setSelected(item.id)}
                    >
                      <span>
                        {item.title}
                        <small className="tnum">
                          {item.steps.length} steps / {new Date(item.created_at * 1000).toLocaleString()}
                        </small>
                      </span>
                      <StatusChip
                        tone={tone[item.state] || "idle"}
                        className={`task-state task-state--${item.state}`}
                      >
                        {item.state.replaceAll("_", " ")}
                      </StatusChip>
                    </button>
                  ))
                ) : (
                  <EmptyState
                    className="task-queue__empty"
                    title="No plans yet"
                    body="Save a plan, review it here, then approve each step as it runs."
                  />
                )}
              </div>
              {task && (
                <article className="task-queue__receipt">
                  <div className="task-queue__section">
                    <h3>{task.title}</h3>
                    <StatusChip tone={tone[task.state] || "idle"}>{task.state.toUpperCase()}</StatusChip>
                  </div>
                  <ol>
                    {task.steps.map((step, index) => (
                      <li key={index}>
                        <div className="task-queue__receipt-step">
                          <span className="task-queue__num tnum">{String(index + 1).padStart(2, "0")}</span>
                          <strong>{label[step.tool]}</strong>
                          <StatusChip
                            tone={tone[step.state] || "idle"}
                            className={`task-state task-state--${step.state}`}
                          >
                            {step.state.replaceAll("_", " ")}
                          </StatusChip>
                        </div>
                        <pre>{JSON.stringify(step.args, null, 2)}</pre>
                        {step.code && (
                          <p className="task-queue__hint">
                            Receipt: <span className="task-queue__mono">{step.code}</span>
                          </p>
                        )}
                        {step.state === "uncertain" && (
                          <p className="task-queue__error">
                            The action may have taken effect. Inspect its result manually before making a new
                            plan.
                          </p>
                        )}
                        {step.preview !== null && (
                          <details>
                            <summary>Read result / first 4,000 characters</summary>
                            <pre>{step.preview}</pre>
                          </details>
                        )}
                      </li>
                    ))}
                  </ol>
                  <div className="task-queue__actions">
                    {task.state === "draft" && (
                      <button
                        type="button"
                        className="btn btn--secondary"
                        onClick={() => run(task)}
                        disabled={active || busy || !connected}
                      >
                        Review & start
                      </button>
                    )}
                    {["draft", "running"].includes(task.state) && (
                      <button
                        type="button"
                        className="btn btn--danger task-queue__stop"
                        onClick={() =>
                          act(async () => {
                            await client.current.cancel(task.id);
                            return client.current.state();
                          })
                        }
                        disabled={busy || !connected}
                      >
                        <Square size={13} /> Stop task
                      </button>
                    )}
                  </div>
                  {["stopped", "interrupted"].includes(task.state) && (
                    <p className="task-queue__hint">
                      This attempt cannot be resumed or replayed. Review completed and uncertain steps before
                      creating a new plan.
                    </p>
                  )}
                </article>
              )}
              <p className="task-queue__hint">
                <span className="task-queue__mono tnum">
                  {data.receipts_used} / {data.receipt_limit}
                </span>{" "}
                durable IDs used. Up to 24 full plans retained;
                older finished details expire as space is needed. IDs remain reserved.
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
