/** Scoped reminders socket/store registrations. No connection ownership. */
export function registerRemindersEvents({ onSocket, socket, store: useStore, unsubs, deliveredReminderIds }) {
    const s = useStore.getState;
    // --- Reminders ---
    unsubs.push(onSocket('reminder_list', (list) => {
        s().setReminders(Array.isArray(list) ? list : []);
    }));

    unsubs.push(onSocket('reminder_triggered', (data) => {
        if (!data.delivery_id) return;
        if (!deliveredReminderIds.has(data.delivery_id)) {
            s().setActiveAlert(data);
            deliveredReminderIds.add(data.delivery_id);
            if (deliveredReminderIds.size > 512) deliveredReminderIds.delete(deliveredReminderIds.values().next().value);
        }
        socket.emit('acknowledge_reminder', { delivery_id: data.delivery_id });
    }));
    unsubs.push(onSocket('reminder_deliveries', (deliveries) => {
        const alerts = Array.isArray(deliveries) ? deliveries : [];
        s().restoreAlerts(alerts);
        for (const alert of alerts) {
            deliveredReminderIds.add(alert.delivery_id);
            socket.emit('acknowledge_reminder', { delivery_id: alert.delivery_id });
        }
    }));

    unsubs.push(onSocket('reminder_created', (data) => {
        s().addReminder(data);
    }));

    unsubs.push(onSocket('reminder_cancelled', (data) => {
        s().removeReminder(data.id);
    }));

    unsubs.push(onSocket('reminder_updated', () => {
        // No-op: local state already updated by the action that triggered this
    }));

}
