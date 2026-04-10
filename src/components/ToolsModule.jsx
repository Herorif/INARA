import React from 'react';
import { Mic, MicOff, Settings, Power, Video, VideoOff, Hand, Lightbulb, Printer, Globe, Box, Phone, Clock, Monitor } from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';

// Tooltip wrapper — shows label above on hover
const Tip = ({ label, children }) => (
    <div className="relative group flex items-center justify-center">
        {children}
        <span className="absolute -top-9 left-1/2 -translate-x-1/2 px-2 py-1 rounded bg-gray-900 border border-cyan-900/60 text-[9px] font-bold tracking-widest text-cyan-400 whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity duration-150 pointer-events-none">
            {label}
        </span>
    </div>
);

const ToolsModule = ({ position, onMouseDown }) => {
    const isConnected = useStore(s => s.isConnected);
    const isMuted = useStore(s => s.isMuted);
    const isVideoOn = useStore(s => s.isVideoOn);
    const isHandTrackingEnabled = useStore(s => s.isHandTrackingEnabled);
    const showSettings = useStore(s => s.showSettings);
    const showKasaWindow = useStore(s => s.showKasaWindow);
    const showPrinterWindow = useStore(s => s.showPrinterWindow);
    const showCadWindow = useStore(s => s.showCadWindow);
    const showBrowserWindow = useStore(s => s.showBrowserWindow);
    const showPhoneWindow = useStore(s => s.showPhoneWindow);
    const showReminderWindow = useStore(s => s.showReminderWindow);
    const showDesktopWindow  = useStore(s => s.showDesktopWindow);
    const kasaDevices = useStore(s => s.kasaDevices);
    const activeCalls = useStore(s => s.activeCalls);
    const reminders = useStore(s => s.reminders);
    const overdueCount = reminders.filter(r =>
        (r.status === 'pending' || r.status === 'snoozed') && r.trigger_at * 1000 < Date.now()
    ).length;

    const togglePower = useStore(s => s.togglePower);
    const toggleMute = useStore(s => s.toggleMute);

    return (
        <div
            id="tools"
            onMouseDown={onMouseDown}
            className="absolute px-6 py-3 transition-all duration-200 backdrop-blur-xl bg-black/40 border border-white/10 shadow-2xl rounded-full"
            style={{
                left: position.x,
                top: position.y,
                transform: 'translate(-50%, -50%)',
                pointerEvents: 'auto'
            }}
        >
            <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-5 pointer-events-none mix-blend-overlay rounded-full" />

            <div className="flex justify-center gap-6 relative z-10">

                <Tip label={isConnected ? 'DISCONNECT' : 'CONNECT'}>
                    <button
                        onClick={togglePower}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${isConnected
                            ? 'border-green-500 bg-green-500/10 text-green-500 hover:bg-green-500/20 shadow-[0_0_15px_rgba(34,197,94,0.3)]'
                            : 'border-gray-600 bg-gray-600/10 text-gray-500 hover:bg-gray-600/20'}`}
                    >
                        <Power size={24} />
                    </button>
                </Tip>

                <Tip label={isMuted ? 'UNMUTE' : 'MUTE'}>
                    <button
                        onClick={toggleMute}
                        disabled={!isConnected}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${!isConnected
                            ? 'border-gray-800 text-gray-800 cursor-not-allowed'
                            : isMuted
                                ? 'border-red-500 bg-red-500/10 text-red-500 hover:bg-red-500/20 shadow-[0_0_15px_rgba(239,68,68,0.3)]'
                                : 'border-cyan-500 bg-cyan-500/10 text-cyan-500 hover:bg-cyan-500/20 shadow-[0_0_15px_rgba(6,182,212,0.3)]'}`}
                    >
                        {isMuted ? <MicOff size={24} /> : <Mic size={24} />}
                    </button>
                </Tip>

                <Tip label={isVideoOn ? 'CAMERA OFF' : 'CAMERA ON'}>
                    <button
                        onClick={() => useStore.getState().toggleVideo?.() || useStore.setState(s => ({ isVideoOn: !s.isVideoOn }))}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${isVideoOn
                            ? 'border-purple-500 bg-purple-500/10 text-purple-500 hover:bg-purple-500/20 shadow-[0_0_15px_rgba(168,85,247,0.3)]'
                            : 'border-cyan-900 text-cyan-700 hover:border-cyan-500 hover:text-cyan-500'}`}
                    >
                        {isVideoOn ? <Video size={24} /> : <VideoOff size={24} />}
                    </button>
                </Tip>

                <Tip label="SETTINGS">
                    <button
                        onClick={() => useStore.setState(s => ({ showSettings: !s.showSettings }))}
                        className={`p-3 rounded-full border-2 transition-all ${showSettings
                            ? 'border-cyan-400 text-cyan-400 bg-cyan-900/20'
                            : 'border-cyan-900 text-cyan-700 hover:border-cyan-500 hover:text-cyan-500'}`}
                    >
                        <Settings size={24} />
                    </button>
                </Tip>

                <Tip label="HAND TRACK">
                    <button
                        onClick={() => useStore.setState(s => ({ isHandTrackingEnabled: !s.isHandTrackingEnabled }))}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${isHandTrackingEnabled
                            ? 'border-orange-500 bg-orange-500/10 text-orange-500 hover:bg-orange-500/20 shadow-[0_0_15px_rgba(249,115,22,0.3)]'
                            : 'border-cyan-900 text-cyan-700 hover:border-cyan-500 hover:text-cyan-500'}`}
                    >
                        <Hand size={24} />
                    </button>
                </Tip>

                <Tip label="SMART HOME">
                    <button
                        onClick={() => {
                            if (!showKasaWindow && kasaDevices.length === 0) emitSocket('discover_kasa');
                            useStore.setState(s => ({ showKasaWindow: !s.showKasaWindow }));
                        }}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${showKasaWindow
                            ? 'border-yellow-300 bg-yellow-300/10 text-yellow-300 hover:bg-yellow-300/20 shadow-[0_0_15px_rgba(253,224,71,0.3)]'
                            : 'border-cyan-900 text-cyan-700 hover:border-cyan-500 hover:text-cyan-500'}`}
                    >
                        <Lightbulb size={24} />
                    </button>
                </Tip>

                <Tip label="PRINTERS">
                    <button
                        onClick={() => useStore.setState(s => ({ showPrinterWindow: !s.showPrinterWindow }))}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${showPrinterWindow
                            ? 'border-green-400 bg-green-400/10 text-green-400 hover:bg-green-400/20'
                            : 'border-cyan-900 text-cyan-700 hover:border-green-500 hover:text-green-500'}`}
                    >
                        <Printer size={24} />
                    </button>
                </Tip>

                <Tip label="CAD">
                    <button
                        onClick={() => useStore.setState(s => ({ showCadWindow: !s.showCadWindow }))}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${showCadWindow
                            ? 'border-cyan-400 bg-cyan-400/10 text-cyan-400 hover:bg-cyan-400/20 shadow-[0_0_15px_rgba(34,211,238,0.3)]'
                            : 'border-cyan-900 text-cyan-700 hover:border-cyan-500 hover:text-cyan-500'}`}
                    >
                        <Box size={24} />
                    </button>
                </Tip>

                <Tip label="BROWSER">
                    <button
                        onClick={() => useStore.setState(s => ({ showBrowserWindow: !s.showBrowserWindow }))}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${showBrowserWindow
                            ? 'border-blue-400 bg-blue-400/10 text-blue-400 hover:bg-blue-400/20 shadow-[0_0_15px_rgba(96,165,250,0.3)]'
                            : 'border-cyan-900 text-cyan-700 hover:border-blue-500 hover:text-blue-500'}`}
                    >
                        <Globe size={24} />
                    </button>
                </Tip>

                <Tip label="DESKTOP">
                    <button
                        onClick={() => useStore.setState(s => ({ showDesktopWindow: !s.showDesktopWindow }))}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${showDesktopWindow
                            ? 'border-cyan-400 bg-cyan-400/10 text-cyan-400 hover:bg-cyan-400/20 shadow-[0_0_15px_rgba(34,211,238,0.3)]'
                            : 'border-cyan-900 text-cyan-700 hover:border-cyan-500 hover:text-cyan-500'}`}
                    >
                        <Monitor size={24} />
                    </button>
                </Tip>

                <Tip label="REMINDERS">
                    <button
                        onClick={() => useStore.setState(s => ({ showReminderWindow: !s.showReminderWindow }))}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${showReminderWindow
                            ? 'border-amber-400 bg-amber-400/10 text-amber-400 hover:bg-amber-400/20 shadow-[0_0_15px_rgba(251,191,36,0.3)]'
                            : overdueCount > 0
                                ? 'border-red-500 bg-red-500/10 text-red-400 animate-pulse'
                                : 'border-cyan-900 text-cyan-700 hover:border-amber-500 hover:text-amber-400'}`}
                    >
                        <Clock size={24} />
                        {overdueCount > 0 && (
                            <span className="absolute top-0 right-0 w-4 h-4 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center translate-x-1 -translate-y-1">
                                {overdueCount}
                            </span>
                        )}
                    </button>
                </Tip>

                <Tip label={activeCalls.length > 0 ? `${activeCalls.length} ACTIVE` : 'PHONE'}>
                    <button
                        onClick={() => useStore.setState(s => ({ showPhoneWindow: !s.showPhoneWindow }))}
                        className={`p-3 rounded-full border-2 transition-all duration-300 ${showPhoneWindow
                            ? 'border-green-400 bg-green-400/10 text-green-400 hover:bg-green-400/20 shadow-[0_0_15px_rgba(74,222,128,0.3)]'
                            : activeCalls.length > 0
                                ? 'border-green-500 bg-green-500/10 text-green-500'
                                : 'border-cyan-900 text-cyan-700 hover:border-green-500 hover:text-green-500'}`}
                    >
                        <Phone size={24} />
                        {activeCalls.length > 0 && (
                            <span className="absolute top-0 right-0 w-4 h-4 rounded-full bg-green-500 text-black text-[9px] font-bold flex items-center justify-center translate-x-1 -translate-y-1">
                                {activeCalls.length}
                            </span>
                        )}
                    </button>
                </Tip>

            </div>
        </div>
    );
};

export default ToolsModule;
