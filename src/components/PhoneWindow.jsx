import React, { useState } from 'react';
import { Phone, PhoneOff, PhoneIncoming, PhoneMissed, Delete, Clock } from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';

// ---------------------------------------------------------------------------
// Dial Pad Button
// ---------------------------------------------------------------------------
const DialKey = ({ label, sub, onClick }) => (
    <button
        onClick={onClick}
        className="flex flex-col items-center justify-center p-3 rounded-xl border border-cyan-900/50 bg-black/40 hover:bg-cyan-900/20 hover:border-cyan-500/50 transition-all duration-150 active:scale-95"
    >
        <span className="text-lg font-bold text-cyan-200 leading-none">{label}</span>
        {sub && <span className="text-[9px] text-cyan-600 tracking-widest mt-0.5">{sub}</span>}
    </button>
);

const DIAL_KEYS = [
    { label: '1', sub: '' },    { label: '2', sub: 'ABC' }, { label: '3', sub: 'DEF' },
    { label: '4', sub: 'GHI' }, { label: '5', sub: 'JKL' }, { label: '6', sub: 'MNO' },
    { label: '7', sub: 'PQRS'},{ label: '8', sub: 'TUV' }, { label: '9', sub: 'WXYZ'},
    { label: '*', sub: '' },    { label: '0', sub: '+' },   { label: '#', sub: '' },
];

// ---------------------------------------------------------------------------
// Incoming Call Banner
// ---------------------------------------------------------------------------
const IncomingCallBanner = ({ call, onAnswer, onReject }) => (
    <div className="mx-3 mb-3 p-3 rounded-xl border border-green-500/40 bg-green-500/10 animate-pulse">
        <div className="flex items-center gap-2 mb-2">
            <PhoneIncoming size={16} className="text-green-400" />
            <span className="text-xs font-bold tracking-widest text-green-400">INCOMING CALL</span>
        </div>
        <div className="text-sm font-bold text-white mb-3 font-mono tracking-wider">
            {call.remote_number}
        </div>
        <div className="flex gap-2">
            <button
                onClick={() => onAnswer(call.call_id)}
                className="flex-1 flex items-center justify-center gap-2 py-2 rounded-lg bg-green-500/20 border border-green-500/50 text-green-400 hover:bg-green-500/30 transition-all text-xs font-bold tracking-widest"
            >
                <Phone size={14} /> ANSWER
            </button>
            <button
                onClick={() => onReject(call.call_id)}
                className="flex-1 flex items-center justify-center gap-2 py-2 rounded-lg bg-red-500/20 border border-red-500/50 text-red-400 hover:bg-red-500/30 transition-all text-xs font-bold tracking-widest"
            >
                <PhoneOff size={14} /> REJECT
            </button>
        </div>
    </div>
);

// ---------------------------------------------------------------------------
// Active Call Row
// ---------------------------------------------------------------------------
const ActiveCallRow = ({ call, onHangUp }) => (
    <div className="flex items-center justify-between px-3 py-2 rounded-lg border border-cyan-500/20 bg-cyan-500/5">
        <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
            <div>
                <div className="text-xs font-bold text-cyan-200 tracking-wider font-mono">
                    {call.remote_number}
                </div>
                <div className="text-[10px] text-cyan-600 capitalize">{call.direction}</div>
            </div>
        </div>
        <button
            onClick={() => onHangUp(call.call_id)}
            className="p-2 rounded-lg bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30 transition-all"
        >
            <PhoneOff size={14} />
        </button>
    </div>
);

// ---------------------------------------------------------------------------
// History Row
// ---------------------------------------------------------------------------
const HistoryRow = ({ call }) => {
    const icon = call.direction === 'inbound'
        ? <PhoneIncoming size={12} className="text-cyan-400" />
        : <Phone size={12} className="text-purple-400" />;
    const durationStr = call.duration ? `${Math.round(call.duration)}s` : '';

    return (
        <div className="flex items-center justify-between px-3 py-1.5 rounded-lg hover:bg-white/5 transition-colors">
            <div className="flex items-center gap-2">
                {icon}
                <span className="text-xs font-mono text-cyan-300">{call.remote_number}</span>
            </div>
            <div className="flex items-center gap-1 text-[10px] text-cyan-700">
                {durationStr && <><Clock size={9} /> {durationStr}</>}
            </div>
        </div>
    );
};

// ---------------------------------------------------------------------------
// PhoneWindow
// ---------------------------------------------------------------------------
const PhoneWindow = ({ position, onClose, onMouseDown, zIndex, activeDragElement }) => {
    const [dialInput, setDialInput] = useState('');
    const [tab, setTab] = useState('dial'); // 'dial' | 'history'

    const incomingCall = useStore(s => s.incomingCall);
    const activeCalls = useStore(s => s.activeCalls);
    const callHistory = useStore(s => s.callHistory);

    const handleDial = (key) => setDialInput(prev => prev + key);
    const handleBackspace = () => setDialInput(prev => prev.slice(0, -1));

    const handleCall = () => {
        if (!dialInput.trim()) return;
        emitSocket('user_input', { text: `Call ${dialInput}` });
        setDialInput('');
    };

    const handleAnswer = (call_id) => emitSocket('answer_call', { call_id });
    const handleReject = (call_id) => emitSocket('reject_call', { call_id });
    const handleHangUp = (call_id) => emitSocket('user_input', { text: `End call ${call_id}` });

    return (
        <div
            id="phone"
            className={`absolute flex flex-col backdrop-blur-xl bg-black/80 border border-white/10 shadow-2xl rounded-2xl overflow-hidden transition-all duration-200
                ${activeDragElement === 'phone' ? 'ring-2 ring-green-500 bg-green-500/5' : ''}`}
            style={{
                left: position?.x || window.innerWidth / 2,
                top: position?.y || window.innerHeight / 2,
                transform: 'translate(-50%, -50%)',
                width: 340,
                pointerEvents: 'auto',
                zIndex,
            }}
            onMouseDown={onMouseDown}
        >
            {/* Header */}
            <div
                data-drag-handle
                className="h-9 bg-gray-900/80 border-b border-cyan-500/20 flex items-center justify-between px-3 cursor-grab active:cursor-grabbing shrink-0"
            >
                <div className="flex items-center gap-2">
                    <Phone size={12} className="text-cyan-500" />
                    <span className="text-xs font-bold tracking-widest text-cyan-500/70">PHONE</span>
                    {activeCalls.length > 0 && (
                        <span className="w-4 h-4 rounded-full bg-green-500 text-black text-[9px] font-bold flex items-center justify-center">
                            {activeCalls.length}
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

            <div className="flex-1 flex flex-col gap-2 py-2 overflow-y-auto">

                {/* Incoming call banner */}
                {incomingCall && (
                    <IncomingCallBanner
                        call={incomingCall}
                        onAnswer={handleAnswer}
                        onReject={handleReject}
                    />
                )}

                {/* Active calls */}
                {activeCalls.length > 0 && (
                    <div className="px-3 space-y-1">
                        <div className="text-[10px] text-cyan-700 tracking-widest mb-1">ACTIVE</div>
                        {activeCalls.map(call => (
                            <ActiveCallRow key={call.call_id} call={call} onHangUp={handleHangUp} />
                        ))}
                    </div>
                )}

                {/* Tabs */}
                <div className="flex gap-1 px-3">
                    {['dial', 'history'].map(t => (
                        <button
                            key={t}
                            onClick={() => setTab(t)}
                            className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold tracking-widest transition-all
                                ${tab === t
                                    ? 'bg-cyan-500/20 border border-cyan-500/40 text-cyan-400'
                                    : 'border border-transparent text-cyan-700 hover:text-cyan-500'}`}
                        >
                            {t.toUpperCase()}
                        </button>
                    ))}
                </div>

                {tab === 'dial' && (
                    <>
                        {/* Number display */}
                        <div className="mx-3 flex items-center gap-2 px-3 py-2 rounded-xl border border-cyan-900/50 bg-black/40">
                            <span className="flex-1 text-lg font-mono font-bold text-cyan-200 tracking-widest min-h-[28px]">
                                {dialInput || <span className="text-cyan-800">enter number</span>}
                            </span>
                            {dialInput && (
                                <button onClick={handleBackspace} className="text-cyan-600 hover:text-cyan-400 transition-colors p-1">
                                    <Delete size={16} />
                                </button>
                            )}
                        </div>

                        {/* Dial pad */}
                        <div className="mx-3 grid grid-cols-3 gap-2">
                            {DIAL_KEYS.map(k => (
                                <DialKey key={k.label} label={k.label} sub={k.sub} onClick={() => handleDial(k.label)} />
                            ))}
                        </div>

                        {/* Call button */}
                        <div className="mx-3">
                            <button
                                onClick={handleCall}
                                disabled={!dialInput.trim()}
                                className={`w-full py-3 rounded-xl flex items-center justify-center gap-2 font-bold text-sm tracking-widest transition-all
                                    ${dialInput.trim()
                                        ? 'bg-green-500/20 border border-green-500/50 text-green-400 hover:bg-green-500/30 shadow-[0_0_15px_rgba(34,197,94,0.2)]'
                                        : 'bg-gray-900/40 border border-gray-800 text-gray-700 cursor-not-allowed'}`}
                            >
                                <Phone size={18} /> CALL
                            </button>
                        </div>
                    </>
                )}

                {tab === 'history' && (
                    <div className="px-1">
                        {callHistory.length === 0 ? (
                            <div className="text-center text-cyan-800 text-xs py-8 tracking-widest">NO CALL HISTORY</div>
                        ) : (
                            callHistory.map((call, i) => (
                                <HistoryRow key={call.call_id || i} call={call} />
                            ))
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default PhoneWindow;
