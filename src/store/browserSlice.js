export const createBrowserSlice = (set) => ({
    browserData: { image: null, logs: [] },

    setBrowserData: (updater) => {
        if (typeof updater === 'function') {
            set(state => ({ browserData: updater(state.browserData) }));
        } else {
            set({ browserData: updater });
        }
    },
});
