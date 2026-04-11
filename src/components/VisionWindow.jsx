import React, { useState } from 'react';
import { Eye, EyeOff, Camera, AlertTriangle, Users, Clock, Trash2, Plus } from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';

const formatTime = (ts) => {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

// ---------------------------------------------------------------------------
// Alert row
// ---------------------------------------------------------------------------
const AlertRow = ({ alert }) => (
    <div className="flex items-start gap-2 px-2 py-1.5 rounded hover:bg-white/5 border border-transparent hover:border-red-900/30 transition-all">
        <AlertTriangle size={11} className="text-red-400 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
            <div className="text-[10px] text-red-300 font-mono truncate">{alert.result}</div>
            <div className="text-[9px] text-cyan-900 mt-0.5">{alert.watch_description} · {formatTime(alert.ts)}</div>
        </div>
    </div>
);

// ---------------------------------------------------------------------------
// Watch row
// ---------------------------------------------------------------------------
const WatchRow = ({ watch }) => {
    const handleRemove = () => {
        emitSocket('user_input', { text: `Stop watching for ${watch.id}` });
    };
    return (
        <div className="flex items-center gap-2 px-2 py-1.5 rounded border border-cyan-900/30 bg-black/20">
            <Eye size={11} className="text-cyan-500 shrink-0" />
            <div className="flex-1 min-w-0">
                <div className="text-[10px] text-cyan-300 font-mono truncate">{watch.description}</div>
                <div className="text-[9px] text-cyan-900">id: {watch.id}</div>
            </div>
            <button
                onClick={handleRemove}
                className="text-cyan-900 hover:text-red-400 transition-colors p-1 rounded"
            >
                <Trash2 size={10} />
            </button>
        </div>
    );
};

// ---------------------------------------------------------------------------
// VisionWindow
// ---------------------------------------------------------------------------
const VisionWindow = ({ position, onClose, onMouseDown, zIndex, activeDragElement }) => {
    const [tab, setTab] = useState('watch');
    const [watchInput, setWatchInput] = useState('');

    const activeWatches = useStore(s => s.activeWatches);
    const visionAlerts = useStore(s => s.visionAlerts);
    const lastVisionDescription = useStore(s => s.lastVisionDescription);
    const presenceDetected = useStore(s => s.presenceDetected);

    const handleAsk = (text) => emitSocket('user_input', { text });

    const handleAddWatch = () => {
        if (!watchInput.trim()) return;
        handleAsk(`Watch for: ${watchInput.trim()}`);
        setWatchInput('');
    };

    const TABS = ['watch', 'alerts', 'scene'];
    const alertCount = visionAlerts.length;

    return (
        <div
            id="vision"
            className={`absolute flex flex-col backdrop-blur-xl bg-black/80 border border-white/10 shadow-2xl rounded-2xl overflow-hidden transition-all duration-200
                ${activeDragElement === 'vision' ? 'ring-2 ring-purple-500 bg-purple-500/5' : ''}`}
            style={{
                left: position?.x || window.innerWidth / 2,
                top:  position?.y || window.innerHeight / 2,
                transform: 'translate(-50%, -50%)',
                width: 360,
                pointerEvents: 'auto',
                zIndex,
            }}
            onMouseDown={onMouseDown}
        >
            {/* Header */}
            <div
                data-drag-handle
                className="h-9 bg-gray-900/80 border-b border-purple-500/20 flex items-center justify-between px-3 cursor-grab active:cursor-grabbing shrink-0"
            >
                <div className="flex items-center gap-2">
                    <Eye size={12} className="text-purple-400" />
                    <span className="text-xs font-bold tracking-widest text-purple-400/70">VISION</span>
                    {activeWatches.length > 0 && (
                        <span className="px-1.5 py-0.5 rounded-full bg-purple-500/20 border border-purple-500/40 text-purple-400 text-[9px] font-bold">
                            {activeWatches.length} WATCHING
                        </span>
                    )}
                </div>
                <button
                    onClick={onClose}
                    className="text-gray-400 hover:text-red-400 hover:bg-red-500/20 p-1 rounded transition-colors text-xs"
                >
                    ✕
                </button>
            </div>

            <div className="flex-1 flex flex-col gap-2 py-2 overflow-hidden">
                {/* Tabs */}
                <div className="flex gap-1 px-3">
                    {TABS.map(t => (
                        <button
                            key={t}
                            onClick={() => setTab(t)}
                            className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold tracking-widest transition-all relative
                                ${tab === t
                                    ? 'bg-purple-500/20 border border-purple-500/40 text-purple-400'
                                    : 'border border-transparent text-cyan-700 hover:text-cyan-500'}`}
                        >
                            {t.toUpperCase()}
                            {t === 'alerts' && alertCount > 0 && (
                                <span className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-red-500 text-white text-[8px] font-bold flex items-center justify-center">
                                    {alertCount > 9 ? '9+' : alertCount}
                                </span>
                            )}
                        </button>
                    ))}
                </div>

                <div className="flex-1 overflow-y-auto px-3 space-y-2">

                    {/* WATCH TAB */}
                    {tab === 'watch' && (
                        <>
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    value={watchInput}
                                    onChange={e => setWatchInput(e.target.value)}
                                    onKeyDown={e => e.key === 'Enter' && handleAddWatch()}
                                    placeholder='e.g. "person at door"'
                                    className="flex-1 bg-black/40 border border-cyan-900/50 rounded-lg px-3 py-2 text-[11px] text-cyan-200 placeholder-cyan-900 focus:outline-none focus:border-purple-500/50 font-mono"
                                />
                                <button
                                    onClick={handleAddWatch}
                                    disabled={!watchInput.trim()}
                                    className={`px-3 rounded-lg transition-all ${watchInput.trim()
                                        ? 'bg-purple-500/20 border border-purple-500/40 text-purple-400 hover:bg-purple-500/30'
                                        : 'bg-gray-900/40 border border-gray-800 text-gray-700 cursor-not-allowed'}`}
                                >
                                    <Plus size={14} />
                                </button>
                            </div>

                            {activeWatches.length === 0 ? (
                                <div className="flex flex-col items-center justify-center py-8 gap-2">
                                    <EyeOff size={22} className="text-cyan-900" />
                                    <span className="text-[10px] text-cyan-900 tracking-widest">NO ACTIVE WATCHES</span>
                                </div>
                            ) : (
                                <div className="space-y-1.5">
                                    {activeWatches.map(w => <WatchRow key={w.id} watch={w} />)}
                                </div>
                            )}
                        </>
                    )}

                    {/* ALERTS TAB */}
                    {tab === 'alerts' && (
                        <>
                            {visionAlerts.length === 0 ? (
                                <div className="flex flex-col items-center justify-center py-8 gap-2">
                                    <AlertTriangle size={22} className="text-cyan-900" />
                                    <span className="text-[10px] text-cyan-900 tracking-widest">NO ALERTS YET</span>
                                </div>
                            ) : (
                                <>
                                    <div className="flex justify-end">
                                        <button
                                            onClick={() => useStore.setState({ visionAlerts: [] })}
                                            className="text-[9px] text-cyan-800 hover:text-red-400 transition-colors tracking-widest font-bold flex items-center gap-1"
                                        >
                                            <Trash2 size={9} /> CLEAR
                                        </button>
                                    </div>
                                    <div className="space-y-1">
                                        {visionAlerts.map((a, i) => <AlertRow key={i} alert={a} />)}
                                    </div>
                                </>
                            )}
                        </>
                    )}

                    {/* SCENE TAB */}
                    {tab === 'scene' && (
                        <div className="space-y-3">
                            {/* Presence */}
                            <div className="flex items-center justify-between px-3 py-2 rounded-xl border border-cyan-900/30 bg-black/20">
                                <div className="flex items-center gap-2">
                                    <Users size={14} className="text-cyan-600" />
                                    <span className="text-[10px] text-cyan-600 font-bold tracking-widest">PRESENCE</span>
                                </div>
                                <span className={`text-[10px] font-bold tracking-widest ${
                                    presenceDetected === true ? 'text-green-400' :
                                    presenceDetected === false ? 'text-red-400' :
                                    'text-cyan-900'
                                }`}>
                                    {presenceDetected === true ? 'DETECTED' :
                                     presenceDetected === false ? 'ABSENT' : 'UNKNOWN'}
                                </span>
                            </div>

                            {/* Last description */}
                            {lastVisionDescription ? (
                                <div className="space-y-1">
                                    <div className="text-[9px] text-cyan-800 tracking-widest font-bold">LAST DESCRIPTION</div>
                                    <div className="px-3 py-2 rounded-xl border border-cyan-900/30 bg-black/20 text-[11px] text-cyan-300 leading-relaxed">
                                        {lastVisionDescription}
                                    </div>
                                </div>
                            ) : (
                                <div className="flex flex-col items-center justify-center py-4 gap-1">
                                    <Camera size={18} className="text-cyan-900" />
                                    <span className="text-[9px] text-cyan-900 tracking-widest">ASK INARA WHAT SHE SEES</span>
                                </div>
                            )}

                            {/* Quick actions */}
                            <div className="grid grid-cols-2 gap-2 pt-1 border-t border-cyan-900/30">
                                <button
                                    onClick={() => handleAsk("What do you see right now?")}
                                    className="py-2 rounded-lg border border-purple-900/40 bg-black/30 hover:bg-purple-900/20 text-[10px] text-purple-600 hover:text-purple-400 font-bold tracking-wider flex items-center justify-center gap-1.5 transition-all"
                                >
                                    <Eye size={11} /> DESCRIBE
                                </button>
                                <button
                                    onClick={() => handleAsk("Is anyone in the room?")}
                                    className="py-2 rounded-lg border border-cyan-900/40 bg-black/30 hover:bg-cyan-900/20 text-[10px] text-cyan-600 hover:text-cyan-400 font-bold tracking-wider flex items-center justify-center gap-1.5 transition-all"
                                >
                                    <Users size={11} /> PRESENCE
                                </button>
                            </div>
                        </div>
                    )}

                </div>
            </div>
        </div>
    );
};

export default VisionWindow;
