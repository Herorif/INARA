import React, { useState } from 'react';
import { Bell, Clock, Repeat, Trash2, ChevronRight, BellOff, ToggleLeft, ToggleRight } from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';
import StatusChip from '../shared/ui/StatusChip';
import EmptyState from '../shared/ui/EmptyState';

// Row actions stay hidden until hover, but always appear for keyboard focus and touch.
const REVEAL = 'opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 [@media(pointer:coarse)]:opacity-100';
const ROW = 'group rounded-md border border-line px-3 py-2.5 transition-colors hover:border-line-strong hover:bg-[var(--bg-hover)]';
const META = 'text-[0.6875rem] text-ink-3';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const formatTriggerAt = (ts) => {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  const diffMs = d - now;
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 0) return 'overdue';
  if (diffMins < 60) return `in ${diffMins}m`;
  if (diffMins < 1440) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};

const recurringLabel = (r) => {
  if (!r) return null;
  return { daily: 'Daily', weekly: 'Weekly', weekdays: 'Weekdays' }[r] || r;
};

const triggerLabel = (t) => {
  const map = {
    'greeting:good_morning': 'Good morning',
    'greeting:im_home': "I'm home",
    'greeting:goodnight': 'Goodnight',
    'greeting:leaving': 'Leaving',
    'manual': 'Manual'
  };
  return map[t] || t;
};

// ---------------------------------------------------------------------------
// Reminder Row
// ---------------------------------------------------------------------------
const ReminderRow = ({ reminder }) => {
  const removeReminder = useStore((s) => s.removeReminder);
  const [snoozeOpen, setSnoozeOpen] = useState(false);

  const handleCancel = () => {
    emitSocket('cancel_reminder', { reminder_id: reminder.id });
    removeReminder(reminder.id);
  };

  const handleSnooze = (minutes) => {
    emitSocket('snooze_reminder', { reminder_id: reminder.id, minutes });
    setSnoozeOpen(false);
  };

  const isOverdue = reminder.trigger_at && reminder.trigger_at * 1000 < Date.now();

  return (
    <div className={ROW}>
            <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-2">
                    <Bell size={14} aria-hidden="true" className={`mt-0.5 shrink-0 ${isOverdue ? 'text-danger' : 'text-ink-3'}`} />
                    <div className="min-w-0">
                        <p className="truncate text-sm leading-snug text-ink-1">{reminder.task}</p>
                        <div className="mt-0.5 flex items-center gap-2">
                            <span className={`font-mono text-[0.6875rem] ${isOverdue ? 'text-danger' : 'text-ink-3'}`}>
                                {formatTriggerAt(reminder.trigger_at)}
                            </span>
                            {reminder.recurring &&
              <span className={`flex items-center gap-1 ${META}`}>
                                    <Repeat size={11} aria-hidden="true" />
                                    {recurringLabel(reminder.recurring)}
                                </span>
              }
                        </div>
                    </div>
                </div>

                <div className={`flex shrink-0 items-center gap-1 ${REVEAL}`}>
                    <button
            type="button"
            onClick={() => setSnoozeOpen((v) => !v)}
            className="btn btn--ghost btn--sm btn--icon"
            aria-expanded={snoozeOpen}
            title="Snooze" aria-label={`Snooze ${reminder.task}`}>

                        <Clock size={14} aria-hidden="true" />
                    </button>
                    <button
            type="button"
            onClick={handleCancel}
            className="btn btn--ghost btn--sm btn--icon hover:!text-danger"
            title="Cancel" aria-label={`Cancel ${reminder.task}`}>

                        <Trash2 size={14} aria-hidden="true" />
                    </button>
                </div>
            </div>

            {snoozeOpen &&
      <div className="mt-2 flex gap-1 pl-6">
                    {[5, 15, 30, 60].map((m) =>
        <button
          type="button"
          key={m}
          onClick={() => handleSnooze(m)}
          aria-label={`Snooze ${m} minutes`}
          className="btn btn--secondary btn--sm flex-1 font-mono">

                            {m}m
                        </button>
        )}
                </div>
      }
        </div>);

};

// ---------------------------------------------------------------------------
// Routine Row
// ---------------------------------------------------------------------------
const RoutineRow = ({ routine }) => {
  const handleToggle = () => {
    const action = routine.enabled ? 'disable' : 'enable';
    useStore.getState().sendText(`${action} routine ${routine.name}`);
  };

  return (
    <div className={ROW}>
            <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                    <Repeat size={14} aria-hidden="true" className={routine.enabled ? 'shrink-0 text-ink-2' : 'shrink-0 text-ink-3'} />
                    <div className="min-w-0">
                        <p className="truncate text-sm text-ink-1">{routine.name}</p>
                        <div className={`mt-0.5 flex items-center gap-1 ${META}`}>
                            <span>{triggerLabel(routine.trigger)}</span>
                            <span aria-hidden="true">·</span>
                            <span>{routine.actions?.length || 0} actions</span>
                            <span aria-hidden="true">·</span>
                            <span>{routine.enabled ? 'On' : 'Off'}</span>
                        </div>
                    </div>
                </div>
                <button
          type="button"
          onClick={handleToggle}
          role="switch"
          aria-checked={!!routine.enabled}
          aria-label={`Routine ${routine.name}`}
          className={`btn btn--ghost btn--sm btn--icon shrink-0 ${REVEAL}`}
          title={routine.enabled ? 'Disable' : 'Enable'}>

                    {routine.enabled ?
          <ToggleRight size={18} aria-hidden="true" className="text-accent" /> :
          <ToggleLeft size={18} aria-hidden="true" className="text-ink-3" />
          }
                </button>
            </div>

            {routine.actions && routine.actions.length > 0 &&
      <div className="mt-1.5 space-y-0.5 pl-6">
                    {routine.actions.slice(0, 3).map((action, i) =>
        <div key={i} className={`flex items-center gap-1.5 ${META}`}>
                            <ChevronRight size={11} aria-hidden="true" className="shrink-0" />
                            <span className="truncate">{action}</span>
                        </div>
        )}
                    {routine.actions.length > 3 &&
        <div className={`pl-4 ${META}`}>+{routine.actions.length - 3} more</div>
        }
                </div>
      }
        </div>);

};

// ---------------------------------------------------------------------------
// ReminderWindow
// ---------------------------------------------------------------------------
const TABS = [{ id: 'reminders', label: 'Reminders' }, { id: 'routines', label: 'Routines' }];

const ReminderWindow = () => {
  const [tab, setTab] = useState('reminders');
  const [input, setInput] = useState('');

  const reminders = useStore((s) => s.reminders);
  const routines = useStore((s) => s.routines);

  const pendingReminders = reminders.filter((r) => r.status === 'pending' || r.status === 'snoozed');
  const overdueCount = pendingReminders.filter((r) => r.trigger_at * 1000 < Date.now()).length;

  const handleAsk = () => {
    if (!input.trim()) return;
    useStore.getState().sendText(input);
    setInput('');
  };

  return (
    <div
      id="reminder" className="tool-panel tool-panel--reminder">

            {/* Quick-ask bar */}
            <div className="flex gap-2">
                <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
          placeholder='e.g. "Remind me at 3pm to call the dentist"'
          className="min-w-0 flex-1 px-3 text-sm"
          aria-label="Ask INARA for a reminder or routine" />

                <button
          type="button"
          onClick={handleAsk}
          disabled={!input.trim()}
          className="btn btn--primary disabled:cursor-not-allowed disabled:opacity-40">

                    Ask
                </button>
            </div>

            {overdueCount > 0 &&
      <div><StatusChip tone="danger">{overdueCount} overdue</StatusChip></div>
      }

            {/* Tabs */}
            <div className="hud-tabs" role="group" aria-label="Reminders and routines">
                {TABS.map((t) =>
        <button
          type="button"
          key={t.id}
            aria-pressed={tab === t.id}
          onClick={() => setTab(t.id)}
          className={`hud-tab flex-1 text-sm ${tab === t.id ? 'is-active' : ''}`}>

                        {t.label}
                    </button>
        )}
            </div>

            {/* Content */}
            <div className="flex flex-1 flex-col gap-1.5 overflow-y-auto">
                {tab === 'reminders' && (
        pendingReminders.length === 0 ?
        <EmptyState className="py-10" icon={<BellOff />} title="No reminders" body="Ask INARA to set a reminder for you." /> :

        pendingReminders.
        sort((a, b) => a.trigger_at - b.trigger_at).
        map((r) => <ReminderRow key={r.id} reminder={r} />))
        }

                {tab === 'routines' && (
        routines.length === 0 ?
        <EmptyState className="py-10" icon={<Repeat />} title="No routines" body="Ask INARA to create a routine for you." /> :

        routines.map((r) => <RoutineRow key={r.name} routine={r} />))
        }
            </div>
        </div>);

};

export default ReminderWindow;
