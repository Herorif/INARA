// The window's speaker and webcam choices. The microphone is the core's one Microphone
// setting (voice.local_microphone, see voiceSlice).
export const createDeviceSlice = (set) => ({
    speakerDevices: [],
    webcamDevices: [],
    selectedSpeakerId: localStorage.getItem('selectedSpeakerId') || '',
    selectedWebcamId: localStorage.getItem('selectedWebcamId') || '',

    setSpeakerDevices: (devices) => set({ speakerDevices: devices }),
    setWebcamDevices: (devices) => set({ webcamDevices: devices }),

    setSelectedSpeakerId: (id) => {
        localStorage.setItem('selectedSpeakerId', id);
        set({ selectedSpeakerId: id });
    },
    setSelectedWebcamId: (id) => {
        localStorage.setItem('selectedWebcamId', id);
        set({ selectedWebcamId: id });
    },
});
