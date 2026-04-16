import React, { useState } from 'react';
import { Bell, Clock, Repeat, Trash2, ChevronRight, BellOff, ToggleLeft, ToggleRight } from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const formatTriggerAt = (ts) => {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const now = new Date();
    const diffMs = d - now;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 0)    return 'overdue';
    if (diffMins < 60)   return `in ${diffMins}m`;
    if (diffMins < 1440) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return d.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};

const recurringLabel = (r) => {
    if (!r) return null;
    return { daily: 'Daily', weekly: 'Weekly', weekdays: 'Weekdays' }[r] || r;
};

const triggerLabel = (t) => {
    const map = {
        'greeting:good_morning': 'Good Morning',
        'greeting:im_home':      "I'm Home",
        'greeting:goodnight':    'Goodnight',
        'greeting:leaving':      'Leaving',
        'manual':                'Manual',
    };
    return map[t] || t;
};

// ---------------------------------------------------------------------------
// Reminder Row
// ---------------------------------------------------------------------------
const ReminderRow = ({ reminder }) => {
    const removeReminder = useStore(s => s.removeReminder);
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
        <div className="px-3 py-2.5 rounded-lg border border-white/5 hover:border-cyan-500/20 hover:bg-white/5 transition-all group">
            <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2 min-w-0">
                    <Bell size={12} className={`shrink-0 mt-0.5 ${isOverdue ? 'text-red-400' : 'text-cyan-500'}`} />
                    <div className="min-w-0">
                        <p className="text-xs text-cyan-200 leading-snug truncate">{reminder.task}</p>
                        <div className="flex items-center gap-2 mt-0.5">
                            <span className={`text-[10px] font-mono ${isOverdue ? 'text-red-400' : 'text-cyan-700'}`}>
                                {formatTriggerAt(reminder.trigger_at)}
                            </span>
                            {reminder.recurring && (
                                <span className="flex items-center gap-0.5 text-[9px] text-purple-500">
                                    <Repeat size={8} />
                                    {recurringLabel(reminder.recurring)}
                                </span>
                            )}
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <button
                        onClick={() => setSnoozeOpen(v => !v)}
                        className="p-1 rounded text-cyan-700 hover:text-cyan-400 hover:bg-cyan-900/30 transition-colors"
                        title="Snooze"
                    >
                        <Clock size={11} />
                    </button>
                    <button
                        onClick={handleCancel}
                        className="p-1 rounded text-cyan-700 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                        title="Cancel"
                    >
                        <Trash2 size={11} />
                    </button>
                </div>
            </div>

            {snoozeOpen && (
                <div className="flex gap-1 mt-2 pl-5">
                    {[5, 15, 30, 60].map(m => (
                        <button
                            key={m}
                            onClick={() => handleSnooze(m)}
                            className="flex-1 py-1 rounded text-[9px] font-bold text-cyan-500 border border-cyan-900/50 bg-cyan-900/20 hover:bg-cyan-900/40 transition-colors"
                        >
                            {m}m
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
};

// ---------------------------------------------------------------------------
// Routine Row
// ---------------------------------------------------------------------------
const RoutineRow = ({ routine }) => {
    const handleToggle = () => {
        const action = routine.enabled ? 'disable' : 'enable';
        emitSocket('user_input', { text: `${action} routine ${routine.name}` });
    };

    return (
        <div className="px-3 py-2.5 rounded-lg border border-white/5 hover:border-cyan-500/20 hover:bg-white/5 transition-all group">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <Repeat size={12} className={routine.enabled ? 'text-purple-400 shrink-0' : 'text-gray-600 shrink-0'} />
                    <div className="min-w-0">
                        <p className="text-xs text-cyan-200 truncate">{routine.name}</p>
                        <div className="flex items-center gap-1 mt-0.5">
                            <span className="text-[9px] text-cyan-800 font-mono">{triggerLabel(routine.trigger)}</span>
                            <span className="text-[9px] text-cyan-900">•</span>
                            <span className="text-[9px] text-cyan-800">{routine.actions?.length || 0} actions</span>
                        </div>
                    </div>
                </div>
                <button
                    onClick={handleToggle}
                    className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-cyan-700 hover:text-cyan-400"
                    title={routine.enabled ? 'Disable' : 'Enable'}
                >
                    {routine.enabled
                        ? <ToggleRight size={18} className="text-purple-400" />
                        : <ToggleLeft size={18} className="text-gray-600" />
                    }
                </button>
            </div>

            {routine.actions && routine.actions.length > 0 && (
                <div className="mt-1.5 pl-5 space-y-0.5">
                    {routine.actions.slice(0, 3).map((action, i) => (
                        <div key={i} className="flex items-center gap-1.5 text-[9px] text-cyan-800">
                            <ChevronRight size={8} className="shrink-0" />
                            <span className="truncate">{action}</span>
                        </div>
                    ))}
                    {routine.actions.length > 3 && (
                        <div className="text-[9px] text-cyan-900 pl-3">+{routine.actions.length - 3} more</div>
                    )}
                </div>
            )}
        </div>
    );
};

// ---------------------------------------------------------------------------
// ReminderWindow
// ---------------------------------------------------------------------------
const ReminderWindow = ({ position, onClose, onMouseDown, zIndex, activeDragElement }) => {
    const [tab, setTab] = useState('reminders');
    const [input, setInput] = useState('');

    const reminders = useStore(s => s.reminders);
    const routines  = useStore(s => s.routines);

    const pendingReminders  = reminders.filter(r => r.status === 'pending' || r.status === 'snoozed');
    const overdueCount      = pendingReminders.filter(r => r.trigger_at * 1000 < Date.now()).length;

    const handleAsk = () => {
        if (!input.trim()) return;
        emitSocket('user_input', { text: input });
        setInput('');
    };

    return (
        <div
            id="reminder"
            className={`absolute flex flex-col backdrop-blur-xl bg-black/80 border border-white/10 shadow-2xl rounded-2xl overflow-hidden transition-all duration-200
                ${activeDragElement === 'reminder' ? 'ring-2 ring-amber-500 bg-amber-500/5' : ''}`}
            style={{
                left: position?.x || window.innerWidth / 2,
                top:  position?.y || window.innerHeight / 2,
                transform: 'translate(-50%, -50%)',
                width: 340,
                pointerEvents: 'auto',
                zIndex,
            }}
            onMouseDown={onMouseDown}
        >
            {/* Header */}
            <div
                data-drag-handle
                className="h-9 bg-gray-900/80 border-b border-amber-500/20 flex items-center justify-between px-3 cursor-grab active:cursor-grabbing shrink-0"
            >
                <div className="flex items-center gap-2">
                    <Bell size={12} className="text-amber-400" />
                    <span className="text-xs font-bold tracking-widest text-amber-400/70">REMINDERS</span>
                    {overdueCount > 0 && (
                        <span className="w-4 h-4 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center">
                            {overdueCount}
                        </span>
                    )}
                </div>
                <button
                    onClick={onClose}
                    className="text-gray-400 hover:text-red-400 hover:bg-red-500/20 p-1 rounded transition-colors text-xs"
                >
                    ✕
                </button>
            </div>

            <div className="flex flex-col gap-2 py-2 flex-1 overflow-hidden">
                {/* Quick-ask bar */}
                <div className="mx-3 flex gap-2">
                    <input
                        type="text"
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleAsk()}
                        placeholder='e.g. "Remind me at 3pm to call the dentist"'
                        className="flex-1 bg-black/40 border border-cyan-900/50 rounded-lg px-3 py-2 text-[11px] text-cyan-200 placeholder-cyan-900 focus:outline-none focus:border-cyan-500/50 font-mono"
                    />
                    <button
                        onClick={handleAsk}
                        disabled={!input.trim()}
                        className={`px-3 rounded-lg text-[10px] font-bold tracking-wider transition-all
                            ${input.trim()
                                ? 'bg-amber-500/20 border border-amber-500/40 text-amber-400 hover:bg-amber-500/30'
                                : 'bg-gray-900/40 border border-gray-800 text-gray-700 cursor-not-allowed'}`}
                    >
                        ASK
                    </button>
                </div>

                {/* Tabs */}
                <div className="flex gap-1 px-3">
                    {['reminders', 'routines'].map(t => (
                        <button
                            key={t}
                            onClick={() => setTab(t)}
                            className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold tracking-widest transition-all relative
                                ${tab === t
                                    ? 'bg-amber-500/20 border border-amber-500/40 text-amber-400'
                                    : 'border border-transparent text-cyan-700 hover:text-cyan-500'}`}
                        >
                            {t.toUpperCase()}
                            {t === 'reminders' && overdueCount > 0 && (
                                <span className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-red-500 text-white text-[8px] font-bold flex items-center justify-center">
                                    {overdueCount}
                                </span>
                            )}
                        </button>
                    ))}
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto px-1 space-y-1">
                    {tab === 'reminders' && (
                        pendingReminders.length === 0
                            ? (
                                <div className="flex flex-col items-center justify-center py-10 gap-2">
                                    <BellOff size={24} className="text-cyan-900" />
                                    <span className="text-cyan-800 text-xs tracking-widest">NO REMINDERS</span>
                                    <span className="text-cyan-900 text-[10px] text-center px-6">Ask INARA to set a reminder for you</span>
                                </div>
                            )
                            : pendingReminders
                                .sort((a, b) => a.trigger_at - b.trigger_at)
                                .map(r => <ReminderRow key={r.id} reminder={r} />)
                    )}

                    {tab === 'routines' && (
                        routines.length === 0
                            ? (
                                <div className="flex flex-col items-center justify-center py-10 gap-2">
                                    <Repeat size={24} className="text-cyan-900" />
                                    <span className="text-cyan-800 text-xs tracking-widest">NO ROUTINES</span>
                                    <span className="text-cyan-900 text-[10px] text-center px-6">Ask INARA to create a routine for you</span>
                                </div>
                            )
                            : routines.map(r => <RoutineRow key={r.name} routine={r} />)
                    )}
                </div>
            </div>
        </div>
    );
};

export default ReminderWindow;
