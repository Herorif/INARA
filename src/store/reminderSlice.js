export const createReminderSlice = (set) => ({
    showReminderWindow: false,
    reminders: [],          // pending/snoozed reminder objects from backend
    routines: [],           // routine objects from backend
    activeAlert: null,      // { id, task } when a reminder fires

    setShowReminderWindow: (val) => set({ showReminderWindow: val }),

    setActiveAlert: (alert) => set({ activeAlert: alert }),

    dismissAlert: () => set({ activeAlert: null }),

    setReminders: (reminders) => set({ reminders }),

    setRoutines: (routines) => set({ routines }),

    addReminder: (reminder) => set(state => ({
        reminders: [reminder, ...state.reminders.filter(r => r.id !== reminder.id)],
    })),

    removeReminder: (id) => set(state => ({
        reminders: state.reminders.filter(r => r.id !== id),
        activeAlert: state.activeAlert?.id === id ? null : state.activeAlert,
    })),

    updateReminder: (data) => set(state => ({
        reminders: state.reminders.map(r => r.id === data.id ? { ...r, ...data } : r),
    })),
});
