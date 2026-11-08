/**
 * P2 morning briefing: today's validated card (src/features/briefing/briefingModel.js), or null.
 * The core pushes `briefing` when it shows, plays, dismisses or expires one, and on connect and
 * unlock; locking the workspace clears it until the core sends it again.
 */
export const createBriefingSlice = (set) => ({
    briefing: null,
    setBriefing: (briefing) => set({ briefing }),
});
