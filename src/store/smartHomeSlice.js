export const createSmartHomeSlice = (set) => ({
    showDeviceWindow: false,
    allDevices: [],             // unified Kasa + HA devices

    setAllDevices: (devices) => set({ allDevices: devices }),

    updateDeviceState: (deviceId, updates) => set(state => ({
        allDevices: state.allDevices.map(d =>
            d.id === deviceId ? { ...d, ...updates } : d
        ),
    })),
});
