import React from 'react';
import { X } from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';
import HudLabel from '../shared/ui/HudLabel';

const SNOOZE_OPTIONS = [5, 15, 30];
const alertTime = alert => {
    const seconds = Number(alert.trigger_at);
    const date = Number.isFinite(seconds) && seconds > 0 ? new Date(seconds * 1000) : new Date();
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
};

const ReminderAlert = () => {
    const activeAlert = useStore(s => s.activeAlert);

    if (!activeAlert) return null;

    const handleSnooze = (minutes) => {
        emitSocket('snooze_reminder', { reminder_id: activeAlert.id, delivery_id: activeAlert.delivery_id, minutes });
    };

    const handleDismiss = () => {
        emitSocket('dismiss_reminder', { delivery_id: activeAlert.delivery_id });
    };

    return (
        <section className="reminder-alert hud-panel hud-frame" role="alertdialog" aria-live="assertive" aria-labelledby="reminder-alert-title" aria-describedby="reminder-alert-label">
            <div className="reminder-alert__top">
                <HudLabel id="reminder-alert-label" className="reminder-alert__label">{`REMINDER · ${alertTime(activeAlert)}`}</HudLabel>
                <button type="button" className="btn btn--ghost btn--icon btn--sm reminder-alert__dismiss" aria-label="Dismiss" onClick={handleDismiss}><X size={14} aria-hidden="true" /></button>
            </div>
            <h2 id="reminder-alert-title" className="reminder-alert__title">{activeAlert.task}</h2>
            <div className="reminder-alert__actions">
                <div className="reminder-alert__snooze" role="group" aria-label="Snooze">
                    {SNOOZE_OPTIONS.map((minutes, index) => (
                        <button key={minutes} type="button" className="btn btn--secondary btn--sm" aria-label={`Snooze ${minutes} minutes`} onClick={() => handleSnooze(minutes)}>
                            {index === 0 ? `Snooze ${minutes} min` : `${minutes} min`}
                        </button>
                    ))}
                </div>
                <button type="button" className="btn btn--primary btn--sm" onClick={handleDismiss}>Done</button>
            </div>
        </section>
    );
};

export default ReminderAlert;
