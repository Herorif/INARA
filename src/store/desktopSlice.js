export const createDesktopSlice = (set) => ({
    showDesktopWindow: false,
    systemInfo: null,       // { cpu, memory, disk, battery, processes }
    lastScreenshot: null,   // base64 JPEG string
    runningApps: [],        // [{ pid, name, memory_mb, cpu_percent }]

    setShowDesktopWindow: (val) => set({ showDesktopWindow: val }),
    setSystemInfo: (info) => set({ systemInfo: info }),
    setLastScreenshot: (b64) => set({ lastScreenshot: b64 }),
    setRunningApps: (apps) => set({ runningApps: apps }),
});
