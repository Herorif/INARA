export const createKasaSlice = (set) => ({
    kasaDevices: [],

    setKasaDevices: (devices) => set({ kasaDevices: devices }),

    updateKasaDevice: (data) => {
        set(state => ({
            kasaDevices: state.kasaDevices.map(d => {
                if (d.ip === data.ip) {
                    return {
                        ...d,
                        is_on: data.is_on !== null ? data.is_on : d.is_on,
                        brightness: data.brightness !== null ? data.brightness : d.brightness,
                    };
                }
                return d;
            })
        }));
    },
});
