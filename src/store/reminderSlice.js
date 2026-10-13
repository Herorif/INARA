export const createReminderSlice = (set) => ({
    showReminderWindow: false,
    reminders: [],          // pending/snoozed reminder objects from backend
    routines: [],           // routine objects from backend
    activeAlert: null,      // { id, task } when a reminder fires
    alertQueue: [],

    setShowReminderWindow: (val) => set({ showReminderWindow: val }),

    setActiveAlert: (alert) => set(state => {
        if (!alert || [state.activeAlert, ...state.alertQueue].some(a => a?.delivery_id === alert.delivery_id)) return {};
        return state.activeAlert ? { alertQueue: [...state.alertQueue, alert] }
            : { activeAlert: alert, showReminderWindow: true };
    }),

    restoreAlerts: (alerts) => set({ activeAlert: alerts[0] || null, alertQueue: alerts.slice(1) }),

    dismissAlert: () => set(state => ({ activeAlert: state.alertQueue[0] || null, alertQueue: state.alertQueue.slice(1) })),

    setReminders: (reminders) => set({ reminders }),

    setRoutines: (routines) => set({ routines }),

    addReminder: (reminder) => set(state => ({
        reminders: [reminder, ...state.reminders.filter(r => r.id !== reminder.id)],
    })),

    removeReminder: (id) => set(state => {
        const alerts = [state.activeAlert, ...state.alertQueue].filter(a => a && a.id !== id);
        return { reminders: state.reminders.filter(r => r.id !== id),
            activeAlert: alerts[0] || null, alertQueue: alerts.slice(1) };
    }),

    updateReminder: (data) => set(state => ({
        reminders: state.reminders.map(r => r.id === data.id ? { ...r, ...data } : r),
    })),
});
