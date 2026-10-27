/**
 * Pending tool approvals, oldest first, keyed by request id. `confirmationRequest`
 * mirrors the head so existing readers keep working; a second request no longer
 * replaces the first.
 */
export const enqueueApproval = (queue, request) => {
    if (!request?.id) return queue;
    const index = queue.findIndex(item => item.id === request.id);
    if (index === -1) return [...queue, request];
    return queue.map((item, position) => position === index ? request : item);
};
export const removeApproval = (queue, id) => queue.filter(item => item.id !== id);
const approvalState = queue => ({ confirmationQueue: queue, confirmationRequest: queue[0] || null });

export const createUiSlice = (set, get) => ({
    showQuickAssistant: window.electronAPI?.quickMode === true,
    // performance.now() when the Quick assistant was last opened (hotkey, tray or launch).
    quickOpenedAt: window.electronAPI?.quickMode === true ? performance.now() : null,
    showSettings: false,
    showCapabilities: false,
    showCallLab: false,
    showCadWindow: false,
    showImageStudio: false,
    showBrowserWindow: false,
    showKasaWindow: false,
    showPrinterWindow: false,
    showPhoneWindow: false,
    showDeviceWindow: false,
    isModularMode: false,
    confirmationRequest: null,
    confirmationQueue: [],
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
        device: { w: 360, h: 460 },
    },

    activeDragElement: null,
    zIndexOrder: ['visualizer', 'chat', 'tools', 'video', 'cad', 'browser', 'kasa', 'printer', 'phone', 'reminder', 'desktop', 'device'],

    setShowSettings: (val) => set({ showSettings: val }),
    setShowCadWindow: (val) => set({ showCadWindow: val }),
    setShowBrowserWindow: (val) => set({ showBrowserWindow: val }),
    setShowKasaWindow: (val) => set({ showKasaWindow: val }),
    setShowPrinterWindow: (val) => set({ showPrinterWindow: val }),
    setShowPhoneWindow: (val) => set({ showPhoneWindow: val }),
    setIsModularMode: (val) => set({ isModularMode: val }),
    setConfirmationRequest: (val) => set(state => val
        ? approvalState(enqueueApproval(state.confirmationQueue, val))
        : approvalState(state.confirmationRequest ? removeApproval(state.confirmationQueue, state.confirmationRequest.id) : state.confirmationQueue)),
    enqueueConfirmation: (request) => set(state => approvalState(enqueueApproval(state.confirmationQueue, request))),
    resolveConfirmation: (id) => set(state => approvalState(removeApproval(state.confirmationQueue, id))),
    clearConfirmations: () => set(approvalState([])),
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
