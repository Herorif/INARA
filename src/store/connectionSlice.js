import socket, { emitSocket } from '../services/socket';

export const createConnectionSlice = (set, get) => ({
    // State
    status: 'Disconnected',
    socketConnected: socket.connected,
    isAuthenticated: localStorage.getItem('face_auth_enabled') !== 'true',
    isLockScreenVisible: localStorage.getItem('face_auth_enabled') === 'true',
    faceAuthEnabled: localStorage.getItem('face_auth_enabled') === 'true',
    isConnected: true,
    isMuted: true,
    currentProject: 'default',
    listeningState: 'idle', // 'idle' | 'wake_listening' | 'active'

    // Actions
    setStatus: (status) => set({ status }),
    setSocketConnected: (val) => set({ socketConnected: val }),
    setIsAuthenticated: (val) => set({ isAuthenticated: val }),
    setIsLockScreenVisible: (val) => set({ isLockScreenVisible: val }),
    setFaceAuthEnabled: (val) => {
        localStorage.setItem('face_auth_enabled', val);
        set({ faceAuthEnabled: val });
    },
    setIsConnected: (val) => set({ isConnected: val }),
    setIsMuted: (val) => set({ isMuted: val }),
    setCurrentProject: (val) => set({ currentProject: val }),

    togglePower: () => {
        const { isConnected, micDevices, selectedMicId } = get();
        if (isConnected) {
            emitSocket('stop_audio');
            set({ isConnected: false, isMuted: false });
        } else {
            const index = micDevices.findIndex(d => d.deviceId === selectedMicId);
            emitSocket('start_audio', { device_index: index >= 0 ? index : null });
            set({ isConnected: true, isMuted: false });
        }
    },

    toggleMute: () => {
        const { isConnected, isMuted } = get();
        if (!isConnected) return;
        if (isMuted) {
            emitSocket('resume_audio');
            set({ isMuted: false });
        } else {
            emitSocket('pause_audio');
            set({ isMuted: true });
        }
    },
});
