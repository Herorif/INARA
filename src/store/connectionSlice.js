import socket from '../services/socket';

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
    currentProject: 'temp',
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

    togglePower: () => { set({showQuickAssistant:true}); window.electronAPI?.setQuickMode?.(true); },
    toggleMute: () => { set({showQuickAssistant:true}); window.electronAPI?.setQuickMode?.(true); },
});
