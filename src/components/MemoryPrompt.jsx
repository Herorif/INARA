import React, { useState, useEffect } from 'react';
import { Save, X, Power } from 'lucide-react';

const MemoryPrompt = ({ onConfirm, onDeny, onCancel }) => {
    const [filename, setFilename] = useState('');

    useEffect(() => {
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        setFilename(`memory_${timestamp}`);
    }, []);

    return (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/80 backdrop-blur-sm">
            <div className="bg-black/90 border border-cyan-500/50 rounded-2xl p-8 max-w-md w-full shadow-[0_0_50px_rgba(6,182,212,0.3)] text-center relative overflow-hidden">
                <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-10 pointer-events-none mix-blend-overlay"></div>

                <Save className="w-12 h-12 text-cyan-400 mx-auto mb-4 drop-shadow-[0_0_10px_rgba(34,211,238,0.8)]" />

                <h2 className="text-2xl font-bold text-cyan-100 mb-2 tracking-wider">SAVE MEMORY?</h2>
                <p className="text-cyan-600/80 mb-6 text-sm">
                    Do you want to save this conversation to Long Term Memory?
                </p>

                {/* Filename Input */}
                <div className="mb-6 relative">
                    <label className="block text-xs font-bold text-cyan-700 uppercase tracking-widest mb-2 text-left pl-1">Memory Name</label>
                    <input
                        type="text"
                        value={filename}
                        onChange={(e) => setFilename(e.target.value)}
                        className="w-full bg-black/50 border border-cyan-700/50 rounded-lg p-3 text-cyan-100 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/50 font-mono text-sm"
                        placeholder="Enter filename..."
                    />
                    <div className="absolute right-3 top-[34px] text-cyan-800 text-xs pointer-events-none">.txt</div>
                </div>

                <div className="flex flex-col gap-3">
                    <button
                        onClick={() => onConfirm(filename)}
                        className="w-full bg-cyan-900/40 hover:bg-cyan-800/60 text-cyan-300 border border-cyan-700/50 py-3 rounded-lg transition-all font-bold tracking-widest flex items-center justify-center gap-2 group"
                    >
                        <Save size={18} className="group-hover:scale-110 transition-transform" />
                        YES, SAVE & EXIT
                    </button>

                    <button
                        onClick={onDeny}
                        className="w-full bg-transparent hover:bg-red-900/20 text-red-400 border border-red-900/30 py-3 rounded-lg transition-all font-bold tracking-widest flex items-center justify-center gap-2"
                    >
                        <Power size={18} />
                        NO, JUST EXIT
                    </button>

                    <button
                        onClick={onCancel}
                        className="w-full mt-2 text-cyan-700 hover:text-cyan-500 text-xs tracking-widest uppercase transition-colors"
                    >
                        Cancel
                    </button>
                </div>
            </div>
        </div>
    );
};

export default MemoryPrompt;
