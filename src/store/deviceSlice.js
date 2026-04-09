export const createDeviceSlice = (set) => ({
    micDevices: [],
    speakerDevices: [],
    webcamDevices: [],
    selectedMicId: localStorage.getItem('selectedMicId') || '',
    selectedSpeakerId: localStorage.getItem('selectedSpeakerId') || '',
    selectedWebcamId: localStorage.getItem('selectedWebcamId') || '',

    setMicDevices: (devices) => set({ micDevices: devices }),
    setSpeakerDevices: (devices) => set({ speakerDevices: devices }),
    setWebcamDevices: (devices) => set({ webcamDevices: devices }),

    setSelectedMicId: (id) => {
        localStorage.setItem('selectedMicId', id);
        set({ selectedMicId: id });
    },
    setSelectedSpeakerId: (id) => {
        localStorage.setItem('selectedSpeakerId', id);
        set({ selectedSpeakerId: id });
    },
    setSelectedWebcamId: (id) => {
        localStorage.setItem('selectedWebcamId', id);
        set({ selectedWebcamId: id });
    },
});
