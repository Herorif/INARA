import React, { useState, useEffect } from 'react';
import { X, RefreshCw, Printer, Thermometer, Clock, FileText, ExternalLink } from 'lucide-react';
import useStore from '../store';
import socket, { emitSocket } from '../services/socket';

const PrinterWindow = ({
    position,
    onClose,
    activeDragElement,
    onMouseDown,
    zIndex = 40
}) => {
    const printers = useStore(s => s.printerList);
    const slicingProgress = useStore(s => s.slicingStatus);

    const [isDiscovering, setIsDiscovering] = useState(false);

    useEffect(() => {
        handleDiscover();

        const onPrintResult = (result) => {
            if (result.success) {
                useStore.setState({ slicingStatus: { percent: 100, message: 'Done', active: false } });
            } else {
                useStore.setState({ slicingStatus: { percent: 0, message: 'Failed', active: false } });
            }
        };

        socket.on('print_result', onPrintResult);
        return () => socket.off('print_result', onPrintResult);
    }, []);

    useEffect(() => {
        if (printers.length > 0) setIsDiscovering(false);
    }, [printers]);

    const handleDiscover = () => {
        setIsDiscovering(true);
        emitSocket('discover_printers');
        setTimeout(() => setIsDiscovering(false), 5000);
    };

    const getStatusColor = (state) => {
        if (!state) return 'text-gray-400';
        const s = state.toLowerCase();
        if (s.includes('print')) return 'text-green-400';
        if (s.includes('paus')) return 'text-yellow-400';
        if (s.includes('error') || s.includes('fail')) return 'text-red-400';
        return 'text-cyan-400';
    };

    const openExternal = (url) => {
        if (window.electronAPI) {
            window.electronAPI.openExternal(url);
        }
    };

    return (
        <div
            id="printer"
            onMouseDown={onMouseDown}
            style={{
                position: 'absolute',
                left: position.x,
                top: position.y,
                transform: 'translate(-50%, -50%)',
                width: '380px',
                zIndex: zIndex
            }}
            className="pointer-events-auto backdrop-blur-xl bg-black/80 border border-green-500/30 rounded-2xl shadow-[0_0_30px_rgba(74,222,128,0.1)] overflow-hidden flex flex-col"
        >
            <div data-drag-handle className="flex items-center justify-between p-4 border-b border-white/10 bg-white/5 cursor-grab active:cursor-grabbing">
                <div className="flex items-center gap-2">
                    <Printer size={16} className="text-green-400" />
                    <span className="text-xs font-bold tracking-widest text-green-100 uppercase">3D Printers</span>
                </div>
                <div className="flex items-center gap-2">
                    <button onClick={handleDiscover} disabled={isDiscovering}
                        className={`p-1.5 hover:bg-white/10 rounded-full transition-colors ${isDiscovering ? 'animate-spin text-green-400' : 'text-gray-400 hover:text-green-400'}`}>
                        <RefreshCw size={14} />
                    </button>
                    <button onClick={onClose} className="p-1.5 hover:bg-white/10 rounded-full text-gray-400 hover:text-white transition-colors">
                        <X size={14} />
                    </button>
                </div>
            </div>

            <div className="p-4 max-h-[400px] overflow-y-auto custom-scrollbar">
                <div className="mb-4 p-3 bg-white/5 border border-white/10 rounded-lg">
                    <div className="text-[10px] uppercase text-white/40 font-bold mb-2 tracking-wider">Manual Add</div>
                    <div className="flex flex-col gap-2">
                        <input id="printer-name-input" type="text" placeholder="Printer Name (e.g. Creality K1)"
                            className="w-full bg-black/50 border border-white/10 rounded px-2 py-1 text-xs text-green-100 focus:border-green-500/50 outline-none placeholder:text-white/20" />
                        <div className="flex gap-2">
                            <input id="printer-ip-input" type="text" placeholder="IP Address (e.g. 192.168.1.50)"
                                className="flex-1 bg-black/50 border border-white/10 rounded px-2 py-1 text-xs text-green-100 focus:border-green-500/50 outline-none placeholder:text-white/20"
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        const ip = e.target.value.trim();
                                        const nameInput = document.getElementById('printer-name-input');
                                        const name = nameInput?.value.trim() || ip;
                                        if (ip) {
                                            emitSocket('add_printer', { host: ip, name, type: 'moonraker' });
                                            e.target.value = '';
                                            if (nameInput) nameInput.value = '';
                                            setIsDiscovering(true);
                                        }
                                    }
                                }}
                            />
                            <button className="bg-green-500/20 hover:bg-green-500/30 text-green-400 text-xs px-3 rounded transition-colors"
                                onClick={() => {
                                    const ipInput = document.getElementById('printer-ip-input');
                                    const nameInput = document.getElementById('printer-name-input');
                                    const ip = ipInput?.value.trim();
                                    const name = nameInput?.value.trim() || ip;
                                    if (ip) {
                                        emitSocket('add_printer', { host: ip, name, type: 'moonraker' });
                                        if (ipInput) ipInput.value = '';
                                        if (nameInput) nameInput.value = '';
                                        setIsDiscovering(true);
                                    }
                                }}>
                                Add
                            </button>
                        </div>
                    </div>
                </div>

                {printers.length === 0 ? (
                    <div className="text-center py-8 text-white/30 text-xs">
                        {isDiscovering ? (
                            <div className="flex flex-col items-center gap-2">
                                <RefreshCw className="animate-spin" size={20} />
                                <span>Scanning Network...</span>
                            </div>
                        ) : "No printers found. Try adding IP manually."}
                    </div>
                ) : (
                    <div className="space-y-3">
                        {slicingProgress.active && (
                            <div className="mb-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg">
                                <div className="text-[10px] uppercase text-blue-300 font-bold mb-2 tracking-wider flex justify-between">
                                    <span>Preparation Pipeline</span>
                                    <span>{slicingProgress.percent}%</span>
                                </div>
                                <div className="flex items-center gap-2 mb-2 text-[10px] text-white/40">
                                    <div className={`flex items-center gap-1 ${slicingProgress.percent < 100 ? 'text-green-400 font-bold' : ''}`}>
                                        <div className={`w-2 h-2 rounded-full ${slicingProgress.percent < 100 ? 'bg-green-500 animate-pulse' : 'bg-white/20'}`}></div>
                                        Slicing
                                    </div>
                                    <div className="h-[1px] w-4 bg-white/10"></div>
                                    <div className="flex items-center gap-1">
                                        <div className="w-2 h-2 rounded-full bg-white/20"></div>
                                        Printing
                                    </div>
                                </div>
                                <div className="w-full h-1 bg-white/10 rounded-full overflow-hidden">
                                    <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${slicingProgress.percent}%` }} />
                                </div>
                                <div className="text-[10px] text-blue-200/60 mt-1 truncate">{slicingProgress.message}</div>
                            </div>
                        )}

                        {printers.map((printer, idx) => (
                            <div key={idx} className="bg-white/5 border border-white/10 rounded-lg p-3 hover:border-green-500/30 transition-all">
                                <div className="flex justify-between items-start mb-2">
                                    <div>
                                        <div className="font-bold text-sm text-green-50">{printer.name}</div>
                                        <div className="text-[10px] text-white/40 uppercase tracking-wider">{printer.host}:{printer.port} - {printer.printer_type}</div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <button onClick={() => openExternal(`http://${printer.host}`)}
                                            className="flex items-center gap-1 text-[10px] text-cyan-400 hover:text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 px-2 py-0.5 rounded transition-colors"
                                            title="Open printer web interface">
                                            <ExternalLink size={10} />
                                            <span>Open</span>
                                        </button>
                                        {printer.status && (
                                            <div className={`text-[10px] font-bold px-2 py-0.5 rounded-full bg-white/5 ${getStatusColor(printer.status.state)}`}>
                                                {printer.status.state?.toUpperCase() || "IDLE"}
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {printer.camera_url && (
                                    <div className="mb-3 rounded overflow-hidden border border-white/10 bg-black relative aspect-video">
                                        <img src={printer.camera_url} alt="Printer Camera" className="w-full h-full object-cover"
                                            onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'flex'; }} />
                                        <div className="hidden absolute inset-0 flex items-center justify-center text-white/20 text-xs">
                                            Camera Stream Unavailable
                                        </div>
                                    </div>
                                )}

                                {printer.status && (
                                    <div className="space-y-2 mt-3 pt-3 border-t border-white/5">
                                        {printer.status.progress_percent > 0 && (
                                            <div className="w-full h-1 bg-white/10 rounded-full overflow-hidden">
                                                <div className="h-full bg-green-500 transition-all duration-500" style={{ width: `${printer.status.progress_percent}%` }} />
                                            </div>
                                        )}
                                        <div className="grid grid-cols-2 gap-2 text-[10px] text-white/60">
                                            {printer.status.filename && (
                                                <div className="col-span-2 flex items-center gap-1.5 truncate">
                                                    <FileText size={10} className="text-green-400" />
                                                    <span className="truncate">{printer.status.filename}</span>
                                                </div>
                                            )}
                                            {printer.status.temperatures?.hotend && (
                                                <div className="flex items-center gap-1.5">
                                                    <Thermometer size={10} className="text-red-400" />
                                                    <span>E: {Math.round(printer.status.temperatures.hotend.current)}C</span>
                                                </div>
                                            )}
                                            {printer.status.temperatures?.bed && (
                                                <div className="flex items-center gap-1.5">
                                                    <Thermometer size={10} className="text-blue-400" />
                                                    <span>B: {Math.round(printer.status.temperatures.bed.current)}C</span>
                                                </div>
                                            )}
                                            {printer.status.time_remaining && (
                                                <div className="flex items-center gap-1.5">
                                                    <Clock size={10} className="text-yellow-400" />
                                                    <span>{printer.status.time_remaining} left</span>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};

export default PrinterWindow;
