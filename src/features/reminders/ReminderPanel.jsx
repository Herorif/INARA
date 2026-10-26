import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import useStore from "../../store";
import socket, { emitSocket } from "../../services/socket";
import EmptyState from "../../shared/ui/EmptyState";
import StatusChip from "../../shared/ui/StatusChip";
import "./reminders.css";
export default function ReminderPanel() {
  const reminders = useStore((state) => state.reminders);
  const connected = useStore((state) => state.backendConnected);
  const [creating, setCreating] = useState(false),
    [task, setTask] = useState(""),
    [when, setWhen] = useState("");
  const [recurring, setRecurring] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  useEffect(() => {
    emitSocket("get_reminders");
    const updated = (result) => {
      setBusy(false);
      setMessage(result.message || "Reminder updated.");
      if (result.success) {
        setCreating(false);
        setTask("");
        setWhen("");
      }
    };
    const failed = (result) => {
      setBusy(false);
      setMessage(result.msg || "The reminder could not be updated.");
    };
    socket.on("reminder_updated", updated);
    socket.on("error", failed);
    return () => {
      socket.off("reminder_updated", updated);
      socket.off("error", failed);
    };
  }, []);
  const addButton = (
    <button className="btn btn--primary" disabled={!connected} onClick={() => setCreating(true)}>
      <Plus size={16} />
      Add reminder
    </button>
  );
  return (
    <div className="reminder-panel">
      {(creating || !!reminders.length) && (
        <div className="reminder-toolbar">
          {creating ? (
            <button className="btn btn--ghost" onClick={() => setCreating(false)}>
              Hide form
            </button>
          ) : (
            addButton
          )}
        </div>
      )}
      {creating && (
        <form
          className="reminder-create"
          onSubmit={(event) => {
            event.preventDefault();
            setBusy(true);
            setMessage("");
            emitSocket("create_reminder", {
              task,
              when,
              recurring: recurring || null,
              timezone: "Asia/Kuala_Lumpur",
            });
          }}
        >
          <label>
            What should I remind you about?
            <input
              required
              maxLength={2000}
              value={task}
              onChange={(event) => setTask(event.target.value)}
              placeholder="Reminder text"
            />
          </label>
          <div className="reminder-form-grid">
            <label>
              When · Kuala Lumpur
              <input
                required
                type="datetime-local"
                value={when}
                onChange={(event) => setWhen(event.target.value)}
              />
            </label>
            <label>
              Repeat
              <select value={recurring} onChange={(event) => setRecurring(event.target.value)}>
                <option value="">Just once</option>
                <option value="daily">Every day</option>
                <option value="weekdays">Weekdays</option>
                <option value="weekly">Every week</option>
              </select>
            </label>
          </div>
          <button className="btn btn--primary" disabled={busy || !connected}>
            {busy ? "Awaiting confirmation…" : "Save reminder"}
          </button>
        </form>
      )}
      {message && (
        <p role="status" className="reminder-feedback">
          {message}
        </p>
      )}
      <div className="reminder-list">
        {reminders.length ? (
          reminders.map((reminder) => (
            <article className="reminder-item" key={reminder.id}>
              <div>
                <h4>{reminder.task}</h4>
                <p>
                  <time className="reminder-time tnum">
                    {new Date(reminder.trigger_at * 1000).toLocaleString([], {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                      timeZone: reminder.timezone || "Asia/Kuala_Lumpur",
                    })}
                  </time>
                  {reminder.recurring && (
                    <StatusChip className="reminder-repeat">{reminder.recurring}</StatusChip>
                  )}
                </p>
              </div>
              <button
                className="btn btn--ghost btn--icon btn--sm"
                aria-label={`Cancel reminder: ${reminder.task}`}
                disabled={!connected}
                onClick={() =>
                  emitSocket("cancel_reminder", {
                    reminder_id: reminder.id,
                  })
                }
              >
                <Trash2 size={15} />
              </button>
            </article>
          ))
        ) : (
          <EmptyState
            className="reminder-empty"
            title="No reminders yet"
            body="Reminders work offline and are saved on this PC."
            action={creating ? null : addButton}
          />
        )}
      </div>
      <footer className="reminder-panel-footer">
        <span>Schedules are saved privately on this laptop.</span>
        <button
          className="btn btn--ghost btn--sm"
          onClick={() =>
            useStore.setState({
              showReminderWindow: false,
              showRoutineWindow: true,
            })
          }
        >
          Advanced routines
        </button>
      </footer>
    </div>
  );
}
