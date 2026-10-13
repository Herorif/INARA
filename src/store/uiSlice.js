export const createUiSlice = (set, get) => ({
    showSettings: false,
    showCadWindow: false,
    showBrowserWindow: false,
    showKasaWindow: false,
    showPrinterWindow: false,
    showPhoneWindow: false,
    showVisionWindow: false,
    showDeviceWindow: false,
    isModularMode: false,
    confirmationRequest: null,
    currentTime: new Date(),

    elementPositions: {
        video: { x: 40, y: 80 },
        visualizer: { x: window.innerWidth / 2, y: window.innerHeight / 2 - 150 },
        chat: { x: window.innerWidth / 2, y: window.innerHeight / 2 + 100 },
        cad: { x: window.innerWidth / 2 + 300, y: window.innerHeight / 2 },
        browser: { x: window.innerWidth / 2 - 300, y: window.innerHeight / 2 },
        kasa: { x: window.innerWidth / 2 + 350, y: window.innerHeight / 2 - 100 },
        printer: { x: window.innerWidth / 2 - 350, y: window.innerHeight / 2 - 100 },
        phone: { x: window.innerWidth / 2, y: window.innerHeight / 2 },
        reminder: { x: window.innerWidth / 2 + 200, y: window.innerHeight / 2 - 150 },
        desktop: { x: window.innerWidth / 2 - 200, y: window.innerHeight / 2 - 100 },
        vision: { x: window.innerWidth / 2 + 350, y: window.innerHeight / 2 + 100 },
        device: { x: window.innerWidth / 2 - 350, y: window.innerHeight / 2 + 100 },
        tools: { x: window.innerWidth / 2, y: window.innerHeight - 100 },
    },

    elementSizes: {
        visualizer: { w: 550, h: 350 },
        chat: { w: 550, h: 220 },
        tools: { w: 500, h: 80 },
        cad: { w: 400, h: 400 },
        browser: { w: 550, h: 380 },
        video: { w: 320, h: 180 },
        kasa: { w: 300, h: 380 },
        printer: { w: 380, h: 380 },
        phone: { w: 340, h: 480 },
        reminder: { w: 340, h: 460 },
        desktop: { w: 380, h: 500 },
        vision: { w: 360, h: 440 },
        device: { w: 360, h: 460 },
    },

    activeDragElement: null,
    zIndexOrder: ['visualizer', 'chat', 'tools', 'video', 'cad', 'browser', 'kasa', 'printer', 'phone', 'reminder', 'desktop', 'vision', 'device'],

    setShowSettings: (val) => set({ showSettings: val }),
    setShowCadWindow: (val) => set({ showCadWindow: val }),
    setShowBrowserWindow: (val) => set({ showBrowserWindow: val }),
    setShowKasaWindow: (val) => set({ showKasaWindow: val }),
    setShowPrinterWindow: (val) => set({ showPrinterWindow: val }),
    setShowPhoneWindow: (val) => set({ showPhoneWindow: val }),
    setIsModularMode: (val) => set({ isModularMode: val }),
    setConfirmationRequest: (val) => set({ confirmationRequest: val }),
    setCurrentTime: (val) => set({ currentTime: val }),
    setActiveDragElement: (val) => set({ activeDragElement: val }),
    setElementPositions: (updater) => {
        if (typeof updater === 'function') {
            set(state => ({ elementPositions: updater(state.elementPositions) }));
        } else {
            set({ elementPositions: updater });
        }
    },
    setElementSizes: (updater) => {
        if (typeof updater === 'function') {
            set(state => ({ elementSizes: updater(state.elementSizes) }));
        } else {
            set({ elementSizes: updater });
        }
    },
    setZIndexOrder: (updater) => {
        if (typeof updater === 'function') {
            set(state => ({ zIndexOrder: updater(state.zIndexOrder) }));
        } else {
            set({ zIndexOrder: updater });
        }
    },

    bringToFront: (id) => {
        set(state => ({
            zIndexOrder: [...state.zIndexOrder.filter(el => el !== id), id]
        }));
    },

    getZIndex: (id) => {
        const baseZ = 30;
        const index = get().zIndexOrder.indexOf(id);
        return baseZ + (index >= 0 ? index : 0);
    },

    clampToViewport: (pos, size) => {
        const margin = 10;
        const topBarHeight = 60;
        const width = window.innerWidth;
        const height = window.innerHeight;
        return {
            x: Math.max(size.w / 2 + margin, Math.min(width - size.w / 2 - margin, pos.x)),
            y: Math.max(size.h / 2 + margin + topBarHeight, Math.min(height - size.h / 2 - margin, pos.y))
        };
    },
});
