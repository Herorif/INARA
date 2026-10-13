import socket, { emitSocket } from '../services/socket';

const getConnectionStatus = ({ backendConnected, aiConnected, aiConnecting, aiUnavailable }) => {
    if (!backendConnected) return 'Backend Disconnected';
    if (aiConnecting) return 'AI Connecting';
    if (aiConnected) return 'AI Connected';
    if (aiUnavailable) return 'AI Unavailable';
    return 'Backend Connected';
};

export const createConnectionSlice = (set, get) => ({
    // State
    status: socket.connected ? 'Backend Connected' : 'Backend Disconnected',
    backendConnected: socket.connected,
    isAuthenticated: localStorage.getItem('face_auth_enabled') !== 'true',
    isLockScreenVisible: localStorage.getItem('face_auth_enabled') === 'true',
    faceAuthEnabled: localStorage.getItem('face_auth_enabled') === 'true',
    aiConnected: false,
    aiConnecting: false,
    aiUnavailable: false,
    localDevicesReady: socket.connected,
    isMuted: true,
    currentProject: 'default',
    listeningState: 'idle', // 'idle' | 'wake_listening' | 'active'

    // Actions
    setStatus: (status) => set({ status }),
    setIsAuthenticated: (val) => set({ isAuthenticated: val }),
    setIsLockScreenVisible: (val) => set({ isLockScreenVisible: val }),
    setFaceAuthEnabled: (val) => {
        localStorage.setItem('face_auth_enabled', val);
        set({ faceAuthEnabled: val });
    },
    setIsMuted: (val) => set({ isMuted: val }),
    setCurrentProject: (val) => set({ currentProject: val }),

    togglePower: () => {
        const { aiConnected, aiConnecting, backendConnected, micDevices, selectedMicId } = get();
        if (aiConnecting) return;

        if (aiConnected) {
            emitSocket('stop_audio');
            set({
                aiConnected: false,
                aiConnecting: false,
                aiUnavailable: false,
                isMuted: false,
                status: getConnectionStatus({
                    backendConnected,
                    aiConnected: false,
                    aiConnecting: false,
                    aiUnavailable: false,
                }),
                listeningState: 'idle',
            });
        } else {
            if (!backendConnected) {
                set({ status: 'Backend Disconnected', localDevicesReady: false });
                return;
            }

            const index = micDevices.findIndex(d => d.deviceId === selectedMicId);
            const device = micDevices.find(d => d.deviceId === selectedMicId);

            emitSocket('start_audio', {
                device_index: index >= 0 ? index : null,
                device_name: device ? device.label : null,
                muted: false,
            });
            set({
                aiConnected: false,
                aiConnecting: true,
                aiUnavailable: false,
                status: 'AI Connecting',
                isMuted: false,
            });
        }
    },

    toggleMute: () => {
        const { aiConnected, isMuted } = get();
        if (!aiConnected) return;
        if (isMuted) {
            emitSocket('resume_audio');
            set({ isMuted: false });
        } else {
            emitSocket('pause_audio');
            set({ isMuted: true });
        }
    },
});
