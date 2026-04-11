import React, { useState } from 'react';
import { Cpu, Power, RefreshCw, Lightbulb, Thermometer, Volume2, Tv, ToggleLeft, ToggleRight } from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const DOMAIN_ICONS = {
    light:         Lightbulb,
    switch:        ToggleLeft,
    input_boolean: ToggleLeft,
    climate:       Thermometer,
    media_player:  Tv,
    fan:           Volume2,
    kasa:          Lightbulb,
};

const DOMAIN_COLORS = {
    light:         'text-yellow-400 border-yellow-900/40',
    switch:        'text-cyan-400 border-cyan-900/40',
    input_boolean: 'text-cyan-400 border-cyan-900/40',
    climate:       'text-orange-400 border-orange-900/40',
    media_player:  'text-purple-400 border-purple-900/40',
    fan:           'text-blue-400 border-blue-900/40',
    kasa:          'text-yellow-400 border-yellow-900/40',
    default:       'text-cyan-400 border-cyan-900/40',
};

const SOURCE_BADGE = {
    kasa:           'bg-yellow-500/10 text-yellow-600 border-yellow-900/40',
    home_assistant: 'bg-blue-500/10 text-blue-600 border-blue-900/40',
    default:        'bg-cyan-500/10 text-cyan-700 border-cyan-900/40',
};

const isOn = (device) => {
    const s = (device.state || '').toLowerCase();
    return s === 'on' || s === 'true' || s === 'playing';
};

// ---------------------------------------------------------------------------
// DeviceRow
// ---------------------------------------------------------------------------
const DeviceRow = ({ device }) => {
    const on = isOn(device);
    const domain = device.domain || device.type || 'default';
    const Icon = DOMAIN_ICONS[domain] || Cpu;
    const colorClass = DOMAIN_COLORS[domain] || DOMAIN_COLORS.default;
    const badgeClass = SOURCE_BADGE[device.source] || SOURCE_BADGE.default;

    const handleToggle = () => {
        emitSocket('user_input', {
            text: `${on ? 'Turn off' : 'Turn on'} ${device.name}`,
        });
    };

    return (
        <div className="flex items-center gap-2 px-2 py-2 rounded-lg border border-transparent hover:border-white/5 hover:bg-white/3 transition-all group">
            <div className={`p-1.5 rounded-lg border ${colorClass} bg-black/30`}>
                <Icon size={12} />
            </div>
            <div className="flex-1 min-w-0">
                <div className="text-[11px] text-cyan-200 font-mono truncate">{device.name}</div>
                <div className="flex items-center gap-1.5 mt-0.5">
                    <span className={`text-[8px] font-bold px-1 py-0.5 rounded border ${badgeClass}`}>
                        {device.source === 'home_assistant' ? 'HA' : (device.source || 'N/A').toUpperCase()}
                    </span>
                    <span className={`text-[9px] font-mono ${on ? 'text-green-400' : 'text-gray-600'}`}>
                        {device.state || 'unknown'}
                    </span>
                </div>
            </div>
            <button
                onClick={handleToggle}
                className={`p-1.5 rounded-lg border transition-all ${
                    on
                        ? 'border-green-500/40 bg-green-500/10 text-green-400 hover:bg-green-500/20'
                        : 'border-gray-700 bg-gray-900/40 text-gray-600 hover:border-cyan-700 hover:text-cyan-600'
                }`}
            >
                <Power size={12} />
            </button>
        </div>
    );
};

// ---------------------------------------------------------------------------
// DeviceWindow
// ---------------------------------------------------------------------------
const DeviceWindow = ({ position, onClose, onMouseDown, zIndex, activeDragElement }) => {
    const [filter, setFilter] = useState('all');

    const allDevices = useStore(s => s.allDevices);

    const handleRefresh = () => emitSocket('user_input', { text: 'List all devices' });

    const FILTERS = ['all', 'light', 'switch', 'climate', 'media'];

    const filtered = allDevices.filter(d => {
        if (filter === 'all') return true;
        if (filter === 'media') return d.domain === 'media_player';
        return d.domain === filter || d.type === filter || d.source === filter;
    });

    const onCount = filtered.filter(isOn).length;

    return (
        <div
            id="device"
            className={`absolute flex flex-col backdrop-blur-xl bg-black/80 border border-white/10 shadow-2xl rounded-2xl overflow-hidden transition-all duration-200
                ${activeDragElement === 'device' ? 'ring-2 ring-yellow-400 bg-yellow-400/5' : ''}`}
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
                className="h-9 bg-gray-900/80 border-b border-yellow-400/20 flex items-center justify-between px-3 cursor-grab active:cursor-grabbing shrink-0"
            >
                <div className="flex items-center gap-2">
                    <Cpu size={12} className="text-yellow-400" />
                    <span className="text-xs font-bold tracking-widest text-yellow-400/70">DEVICES</span>
                    {allDevices.length > 0 && (
                        <span className="px-1.5 py-0.5 rounded-full bg-yellow-400/10 border border-yellow-400/30 text-yellow-400 text-[9px] font-bold">
                            {onCount}/{allDevices.length} ON
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={handleRefresh}
                        className="text-cyan-800 hover:text-cyan-400 transition-colors p-1 rounded"
                        title="Refresh device list"
                    >
                        <RefreshCw size={11} />
                    </button>
                    <button
                        onClick={onClose}
                        className="text-gray-400 hover:text-red-400 hover:bg-red-500/20 p-1 rounded transition-colors text-xs"
                    >
                        ✕
                    </button>
                </div>
            </div>

            <div className="flex-1 flex flex-col gap-2 py-2 overflow-hidden">
                {/* Filter pills */}
                <div className="flex gap-1 px-3 overflow-x-auto scrollbar-none">
                    {FILTERS.map(f => (
                        <button
                            key={f}
                            onClick={() => setFilter(f)}
                            className={`shrink-0 px-2.5 py-1 rounded-full text-[9px] font-bold tracking-widest transition-all
                                ${filter === f
                                    ? 'bg-yellow-400/20 border border-yellow-400/40 text-yellow-400'
                                    : 'border border-transparent text-cyan-800 hover:text-cyan-500'}`}
                        >
                            {f.toUpperCase()}
                        </button>
                    ))}
                </div>

                <div className="flex-1 overflow-y-auto px-3 space-y-0.5">
                    {filtered.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-10 gap-2">
                            <Cpu size={24} className="text-cyan-900" />
                            <span className="text-[10px] text-cyan-900 tracking-widest">
                                {allDevices.length === 0 ? 'ASK INARA TO LIST DEVICES' : 'NO DEVICES IN THIS CATEGORY'}
                            </span>
                            {allDevices.length === 0 && (
                                <button
                                    onClick={handleRefresh}
                                    className="mt-1 px-3 py-1.5 rounded-lg border border-yellow-400/30 bg-yellow-400/10 text-yellow-400 hover:bg-yellow-400/20 transition-all text-[10px] font-bold tracking-widest"
                                >
                                    DISCOVER DEVICES
                                </button>
                            )}
                        </div>
                    ) : (
                        filtered.map(d => <DeviceRow key={d.id} device={d} />)
                    )}
                </div>

                {/* Quick commands */}
                {allDevices.length > 0 && (
                    <div className="px-3 pt-1 border-t border-cyan-900/20 flex gap-2">
                        <button
                            onClick={() => emitSocket('user_input', { text: 'Turn off all lights' })}
                            className="flex-1 py-1.5 rounded-lg border border-cyan-900/40 bg-black/20 hover:bg-red-900/20 hover:border-red-900/40 text-[9px] text-cyan-700 hover:text-red-400 font-bold tracking-widest transition-all"
                        >
                            ALL OFF
                        </button>
                        <button
                            onClick={() => emitSocket('user_input', { text: 'Turn on all lights' })}
                            className="flex-1 py-1.5 rounded-lg border border-cyan-900/40 bg-black/20 hover:bg-yellow-900/20 hover:border-yellow-900/40 text-[9px] text-cyan-700 hover:text-yellow-400 font-bold tracking-widest transition-all"
                        >
                            ALL ON
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
};

export default DeviceWindow;
