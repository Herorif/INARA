import React, { useState } from 'react';
import {
    Monitor, Cpu, HardDrive, MemoryStick, Battery, BatteryCharging,
    Search, Clipboard, ClipboardPaste, AppWindow, Camera, Zap,
    Chrome, Terminal, Code, Music, MessageSquare, Globe
} from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const pct = (v) => `${Math.round(v ?? 0)}%`;

const UsageBar = ({ label, percent, color = 'cyan' }) => {
    const colorMap = {
        cyan:   'bg-cyan-500',
        green:  'bg-green-500',
        purple: 'bg-purple-500',
        amber:  'bg-amber-500',
        red:    'bg-red-500',
    };
    const barColor = percent > 90 ? colorMap.red : percent > 70 ? colorMap.amber : colorMap[color];
    return (
        <div className="space-y-1">
            <div className="flex justify-between text-[10px] font-mono">
                <span className="text-cyan-600">{label}</span>
                <span className={percent > 90 ? 'text-red-400' : percent > 70 ? 'text-amber-400' : 'text-cyan-400'}>
                    {pct(percent)}
                </span>
            </div>
            <div className="h-1.5 bg-gray-900 rounded-full overflow-hidden">
                <div
                    className={`h-full rounded-full transition-all duration-500 ${barColor}`}
                    style={{ width: `${Math.min(100, percent ?? 0)}%` }}
                />
            </div>
        </div>
    );
};

// ---------------------------------------------------------------------------
// Quick launch apps
// ---------------------------------------------------------------------------
const QUICK_APPS = [
    { name: 'chrome',    label: 'Chrome',    icon: Globe },
    { name: 'vscode',    label: 'VS Code',   icon: Code },
    { name: 'terminal',  label: 'Terminal',  icon: Terminal },
    { name: 'spotify',   label: 'Spotify',   icon: Music },
    { name: 'discord',   label: 'Discord',   icon: MessageSquare },
    { name: 'explorer',  label: 'Explorer',  icon: HardDrive },
];

const AppButton = ({ app }) => {
    const Icon = app.icon;
    const handleLaunch = () => {
        emitSocket('launch_app', { name: app.name });
    };
    return (
        <button
            onClick={handleLaunch}
            className="flex flex-col items-center gap-1.5 p-3 rounded-xl border border-cyan-900/40 bg-black/30 hover:bg-cyan-900/20 hover:border-cyan-500/40 transition-all group active:scale-95"
        >
            <Icon size={20} className="text-cyan-600 group-hover:text-cyan-400 transition-colors" />
            <span className="text-[9px] text-cyan-700 group-hover:text-cyan-500 font-bold tracking-wider">{app.label}</span>
        </button>
    );
};

// ---------------------------------------------------------------------------
// Stats Panel
// ---------------------------------------------------------------------------
const StatsPanel = ({ info }) => {
    if (!info) {
        return (
            <div className="flex flex-col items-center justify-center py-6 gap-2">
                <Monitor size={24} className="text-cyan-900" />
                <span className="text-cyan-800 text-[10px] tracking-widest">ASK INARA FOR SYSTEM INFO</span>
            </div>
        );
    }

    const { cpu, memory, disk = [], battery } = info;

    return (
        <div className="space-y-3">
            {cpu && (
                <UsageBar
                    label={`CPU — ${cpu.cores ?? '?'} cores${cpu.freq_mhz ? ` @ ${cpu.freq_mhz} MHz` : ''}`}
                    percent={cpu.percent}
                    color="cyan"
                />
            )}
            {memory && (
                <UsageBar
                    label={`RAM — ${memory.used_gb ?? '?'} / ${memory.total_gb ?? '?'} GB`}
                    percent={memory.percent}
                    color="purple"
                />
            )}
            {disk.slice(0, 2).map(d => (
                <UsageBar
                    key={d.mount}
                    label={`Disk ${d.mount} — ${d.used_gb} / ${d.total_gb} GB`}
                    percent={d.percent}
                    color="green"
                />
            ))}
            {battery && (
                <div className="flex items-center justify-between text-[10px] font-mono pt-1 border-t border-cyan-900/30">
                    <div className="flex items-center gap-1.5 text-cyan-600">
                        {battery.plugged_in
                            ? <BatteryCharging size={12} className="text-green-400" />
                            : <Battery size={12} className={battery.percent < 20 ? 'text-red-400' : 'text-cyan-400'} />
                        }
                        <span>Battery</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className={battery.percent < 20 ? 'text-red-400' : 'text-cyan-400'}>
                            {battery.percent}%
                        </span>
                        {battery.plugged_in && <span className="text-green-500">charging</span>}
                        {!battery.plugged_in && battery.time_left_min && (
                            <span className="text-cyan-700">~{battery.time_left_min}m left</span>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

// ---------------------------------------------------------------------------
// Processes list
// ---------------------------------------------------------------------------
const ProcessList = ({ processes }) => {
    if (!processes || processes.length === 0) {
        return <div className="text-[10px] text-cyan-900 text-center py-4">No process data</div>;
    }
    return (
        <div className="space-y-0.5">
            {processes.slice(0, 8).map(p => (
                <div key={p.pid} className="flex items-center justify-between px-2 py-1 rounded hover:bg-white/5 transition-colors">
                    <span className="text-[10px] text-cyan-300 font-mono truncate flex-1 mr-2">{p.name}</span>
                    <div className="flex items-center gap-2 shrink-0">
                        <span className="text-[9px] text-cyan-700 font-mono w-14 text-right">{p.memory_mb} MB</span>
                        {p.cpu_percent > 0 && (
                            <span className="text-[9px] text-amber-600 font-mono w-10 text-right">{p.cpu_percent.toFixed(1)}%</span>
                        )}
                    </div>
                </div>
            ))}
        </div>
    );
};

// ---------------------------------------------------------------------------
// DesktopWindow
// ---------------------------------------------------------------------------
const DesktopWindow = ({ position, onClose, onMouseDown, zIndex, activeDragElement }) => {
    const [tab, setTab] = useState('stats');
    const [searchQuery, setSearchQuery] = useState('');

    const systemInfo    = useStore(s => s.systemInfo);
    const lastScreenshot = useStore(s => s.lastScreenshot);
    const runningApps   = useStore(s => s.runningApps);

    const handleAsk = (text) => emitSocket('user_input', { text });

    const handleSearch = () => {
        if (!searchQuery.trim()) return;
        handleAsk(`Search for files: ${searchQuery}`);
        setSearchQuery('');
    };

    const handleScreenshot = () => emitSocket('take_screenshot', {});
    const handleRefreshStats = () => emitSocket('get_system_info', {});

    const TABS = ['stats', 'apps', 'tools'];

    return (
        <div
            id="desktop"
            className={`absolute flex flex-col backdrop-blur-xl bg-black/80 border border-white/10 shadow-2xl rounded-2xl overflow-hidden transition-all duration-200
                ${activeDragElement === 'desktop' ? 'ring-2 ring-cyan-500 bg-cyan-500/5' : ''}`}
            style={{
                left: position?.x || window.innerWidth / 2,
                top:  position?.y || window.innerHeight / 2,
                transform: 'translate(-50%, -50%)',
                width: 380,
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
                    <Monitor size={12} className="text-cyan-500" />
                    <span className="text-xs font-bold tracking-widest text-cyan-500/70">DESKTOP</span>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={handleRefreshStats}
                        className="text-cyan-800 hover:text-cyan-400 transition-colors p-1 rounded"
                        title="Refresh system info"
                    >
                        <Zap size={11} />
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
                {/* Tabs */}
                <div className="flex gap-1 px-3">
                    {TABS.map(t => (
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

                <div className="flex-1 overflow-y-auto px-3 space-y-3">

                    {/* STATS TAB */}
                    {tab === 'stats' && (
                        <>
                            <StatsPanel info={systemInfo} />
                            {runningApps.length > 0 && (
                                <div>
                                    <div className="text-[9px] text-cyan-800 tracking-widest mb-1 font-bold">PROCESSES</div>
                                    <ProcessList processes={runningApps} />
                                </div>
                            )}
                        </>
                    )}

                    {/* APPS TAB */}
                    {tab === 'apps' && (
                        <>
                            <div className="grid grid-cols-3 gap-2">
                                {QUICK_APPS.map(app => <AppButton key={app.name} app={app} />)}
                            </div>
                            <div className="pt-1 border-t border-cyan-900/30">
                                <div className="text-[9px] text-cyan-800 tracking-widest mb-2 font-bold">LAUNCH ANY APP</div>
                                <div className="flex gap-2">
                                    <input
                                        type="text"
                                        placeholder='App name (e.g. "notepad")'
                                        className="flex-1 bg-black/40 border border-cyan-900/50 rounded-lg px-3 py-2 text-[11px] text-cyan-200 placeholder-cyan-900 focus:outline-none focus:border-cyan-500/50 font-mono"
                                        onKeyDown={e => {
                                            if (e.key === 'Enter' && e.target.value.trim()) {
                                                handleAsk(`Launch ${e.target.value.trim()}`);
                                                e.target.value = '';
                                            }
                                        }}
                                    />
                                </div>
                            </div>
                        </>
                    )}

                    {/* TOOLS TAB */}
                    {tab === 'tools' && (
                        <div className="space-y-3">
                            {/* Screenshot */}
                            <div>
                                <div className="text-[9px] text-cyan-800 tracking-widest mb-2 font-bold">SCREEN VISION</div>
                                {lastScreenshot ? (
                                    <div className="relative rounded-lg overflow-hidden border border-cyan-900/40 mb-2">
                                        <img
                                            src={`data:image/jpeg;base64,${lastScreenshot}`}
                                            alt="Last screenshot"
                                            className="w-full object-cover"
                                            style={{ maxHeight: 140 }}
                                        />
                                        <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
                                        <span className="absolute bottom-1.5 left-2 text-[9px] text-cyan-400 font-bold tracking-wider">LAST CAPTURE</span>
                                    </div>
                                ) : (
                                    <div className="flex flex-col items-center justify-center py-5 border border-dashed border-cyan-900/40 rounded-lg mb-2 gap-1">
                                        <Camera size={20} className="text-cyan-900" />
                                        <span className="text-[9px] text-cyan-900 tracking-widest">NO CAPTURE YET</span>
                                    </div>
                                )}
                                <button
                                    onClick={handleScreenshot}
                                    className="w-full py-2 rounded-lg border border-cyan-500/30 bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 transition-all text-[10px] font-bold tracking-widest flex items-center justify-center gap-2"
                                >
                                    <Camera size={12} /> CAPTURE SCREEN
                                </button>
                            </div>

                            {/* File search */}
                            <div className="border-t border-cyan-900/30 pt-3">
                                <div className="text-[9px] text-cyan-800 tracking-widest mb-2 font-bold">FILE SEARCH</div>
                                <div className="flex gap-2">
                                    <input
                                        type="text"
                                        value={searchQuery}
                                        onChange={e => setSearchQuery(e.target.value)}
                                        onKeyDown={e => e.key === 'Enter' && handleSearch()}
                                        placeholder='e.g. "resume.docx" or "*.pdf"'
                                        className="flex-1 bg-black/40 border border-cyan-900/50 rounded-lg px-3 py-2 text-[11px] text-cyan-200 placeholder-cyan-900 focus:outline-none focus:border-cyan-500/50 font-mono"
                                    />
                                    <button
                                        onClick={handleSearch}
                                        disabled={!searchQuery.trim()}
                                        className={`px-3 rounded-lg transition-all ${searchQuery.trim()
                                            ? 'bg-cyan-500/20 border border-cyan-500/40 text-cyan-400 hover:bg-cyan-500/30'
                                            : 'bg-gray-900/40 border border-gray-800 text-gray-700 cursor-not-allowed'}`}
                                    >
                                        <Search size={14} />
                                    </button>
                                </div>
                            </div>

                            {/* Clipboard */}
                            <div className="border-t border-cyan-900/30 pt-3">
                                <div className="text-[9px] text-cyan-800 tracking-widest mb-2 font-bold">CLIPBOARD</div>
                                <div className="flex gap-2">
                                    <button
                                        onClick={() => handleAsk('Read my clipboard')}
                                        className="flex-1 py-2 rounded-lg border border-cyan-900/40 bg-black/30 hover:bg-cyan-900/20 transition-all text-[10px] text-cyan-600 hover:text-cyan-400 flex items-center justify-center gap-1.5 font-bold tracking-wider"
                                    >
                                        <Clipboard size={11} /> READ
                                    </button>
                                    <button
                                        onClick={() => handleAsk('What did I last copy to clipboard?')}
                                        className="flex-1 py-2 rounded-lg border border-cyan-900/40 bg-black/30 hover:bg-cyan-900/20 transition-all text-[10px] text-cyan-600 hover:text-cyan-400 flex items-center justify-center gap-1.5 font-bold tracking-wider"
                                    >
                                        <ClipboardPaste size={11} /> PASTE TO INARA
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default DesktopWindow;
