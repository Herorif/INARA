import React from 'react';
import { Bell, X, Clock } from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';

const SNOOZE_OPTIONS = [5, 15, 30];

const ReminderAlert = () => {
    const activeAlert = useStore(s => s.activeAlert);
    const dismissAlert = useStore(s => s.dismissAlert);
    const removeReminder = useStore(s => s.removeReminder);

    if (!activeAlert) return null;

    const handleSnooze = (minutes) => {
        emitSocket('user_input', {
            text: `Snooze reminder ${activeAlert.id.slice(0, 8)} for ${minutes} minutes`,
        });
        dismissAlert();
    };

    const handleDismiss = () => {
        removeReminder(activeAlert.id);
        dismissAlert();
    };

    return (
        <div className="fixed top-20 left-1/2 -translate-x-1/2 z-[200] w-[360px] pointer-events-auto">
            {/* Outer glow ring */}
            <div className="absolute inset-0 rounded-2xl border border-amber-400/60 animate-pulse pointer-events-none" />

            <div className="relative backdrop-blur-xl bg-black/90 border border-amber-500/40 rounded-2xl shadow-[0_0_40px_rgba(251,191,36,0.15)] overflow-hidden">
                {/* Top accent bar */}
                <div className="h-0.5 w-full bg-gradient-to-r from-transparent via-amber-400/60 to-transparent" />

                <div className="p-4">
                    {/* Header */}
                    <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                            <div className="p-1.5 rounded-lg bg-amber-500/20 border border-amber-500/30">
                                <Bell size={14} className="text-amber-400" />
                            </div>
                            <span className="text-[10px] font-bold tracking-widest text-amber-400">REMINDER</span>
                        </div>
                        <button
                            onClick={handleDismiss}
                            className="p-1 rounded text-gray-600 hover:text-gray-300 hover:bg-white/5 transition-colors"
                        >
                            <X size={14} />
                        </button>
                    </div>

                    {/* Task text */}
                    <p className="text-sm text-white font-mono leading-relaxed mb-4 pl-1">
                        {activeAlert.task}
                    </p>

                    {/* Actions */}
                    <div className="flex gap-2">
                        <div className="flex gap-1 flex-1">
                            {SNOOZE_OPTIONS.map(m => (
                                <button
                                    key={m}
                                    onClick={() => handleSnooze(m)}
                                    className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg border border-cyan-900/60 bg-cyan-900/20 text-cyan-500 hover:bg-cyan-900/40 hover:border-cyan-500/50 transition-all text-[10px] font-bold tracking-wider"
                                >
                                    <Clock size={9} />
                                    {m}m
                                </button>
                            ))}
                        </div>
                        <button
                            onClick={handleDismiss}
                            className="px-3 py-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-all text-[10px] font-bold tracking-wider"
                        >
                            DONE
                        </button>
                    </div>
                </div>

                <div className="h-0.5 w-full bg-gradient-to-r from-transparent via-amber-400/20 to-transparent" />
            </div>
        </div>
    );
};

export default ReminderAlert;
