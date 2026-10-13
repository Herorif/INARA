export const createPhoneSlice = (set) => ({
    showPhoneWindow: false,
    activeCalls: [],       // CallInfo objects currently connected
    callHistory: [],       // Ended calls (last 20)
    incomingCall: null,    // CallInfo when ringing, null otherwise

    setShowPhoneWindow: (val) => set({ showPhoneWindow: val }),

    setIncomingCall: (call) => set({ incomingCall: call }),

    addActiveCall: (call) => set(state => ({
        activeCalls: [...state.activeCalls.filter(c => c.call_id !== call.call_id), call],
        incomingCall: state.incomingCall?.call_id === call.call_id ? null : state.incomingCall,
    })),

    updateCallStatus: (data) => set(state => ({
        activeCalls: state.activeCalls.map(c =>
            c.call_id === data.call_id ? { ...c, ...data } : c
        ),
    })),

    removeActiveCall: (call) => set(state => ({
        activeCalls: state.activeCalls.filter(c => c.call_id !== call.call_id),
        callHistory: [call, ...state.callHistory].slice(0, 20),
    })),
});
