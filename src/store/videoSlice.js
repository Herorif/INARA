export const createVideoSlice = (set) => ({
    isVideoOn: false,
    fps: 0,
    isHandTrackingEnabled: false,
    cursorSensitivity: 2.0,
    isCameraFlipped: false,
    cursorPos: { x: 0, y: 0 },
    isPinching: false,
    ripples: [],

    setIsVideoOn: (val) => set({ isVideoOn: val }),
    setFps: (val) => set({ fps: val }),
    setIsHandTrackingEnabled: (val) => set({ isHandTrackingEnabled: val }),
    setCursorSensitivity: (val) => set({ cursorSensitivity: val }),
    setIsCameraFlipped: (val) => set({ isCameraFlipped: val }),
    setCursorPos: (val) => set({ cursorPos: val }),
    setIsPinching: (val) => set({ isPinching: val }),
    setRipples: (val) => set({ ripples: val }),
});
