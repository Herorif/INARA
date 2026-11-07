/**
 * The owner's live design (docs/LIVE_DESIGN.md): the core's validated `cad_design` snapshot
 * (src/features/liveDesign/model.js), kept while the core is offline, and the panel's state.
 * - liveDesign: the design or null; liveDesignReady: a snapshot arrived since the page loaded.
 * - liveDesignSeen: { id, n }, the newest step the panel has shown (drives the reveal and banner).
 * - liveDesignPanelVisible: the panel is mounted and on screen (it answers its own approvals).
 * - cadDraftHandoff: { recipe }, a draft the 3D studio adopts once when it mounts.
 */
export const createLiveDesignSlice = (set) => ({
    liveDesign: null,
    liveDesignReady: false,
    liveDesignSeen: null,
    liveDesignPanelVisible: false,
    cadDraftHandoff: null,
    setLiveDesignSeen: (seen) => set({ liveDesignSeen: seen }),
});
