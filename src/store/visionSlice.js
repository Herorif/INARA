export const createVisionSlice = (set) => ({
    showVisionWindow: false,
    activeWatches: [],          // [{ id, description, added_at }]
    visionAlerts: [],           // [{ watch_id, watch_description, result, ts }]
    lastVisionDescription: '',
    presenceDetected: null,     // null | true | false

    setActiveWatches: (watches) => set({ activeWatches: watches }),

    addVisionAlert: (alert) => set(state => ({
        visionAlerts: [{ ...alert, ts: Date.now() }, ...state.visionAlerts].slice(0, 20),
    })),

    clearVisionAlerts: () => set({ visionAlerts: [] }),

    setLastVisionDescription: (desc) => set({ lastVisionDescription: desc }),

    setPresenceDetected: (val) => set({ presenceDetected: val }),
});
