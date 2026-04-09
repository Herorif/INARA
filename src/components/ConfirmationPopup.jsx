import React from 'react';
import useStore from '../store';
import { emitSocket } from '../services/socket';

const ConfirmationPopup = () => {
    const request = useStore(s => s.confirmationRequest);
    const setConfirmationRequest = useStore(s => s.setConfirmationRequest);

    if (!request) return null;

    const handleConfirm = () => {
        emitSocket('confirm_tool', { id: request.id, confirmed: true });
        setConfirmationRequest(null);
    };

    const handleDeny = () => {
        emitSocket('confirm_tool', { id: request.id, confirmed: false });
        setConfirmationRequest(null);
    };

    return (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
            <div className="relative w-full max-w-lg p-8 bg-black/90 border border-cyan-500/30 rounded-3xl shadow-[0_0_50px_rgba(34,211,238,0.15)] backdrop-blur-2xl transform transition-all scale-100">
                <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-10 pointer-events-none mix-blend-overlay rounded-3xl"></div>

                <div className="flex items-center gap-4 mb-6 relative z-10">
                    <div className="p-3 rounded-full bg-cyan-900/30 border border-cyan-500/50 text-cyan-400 shadow-[0_0_15px_rgba(34,211,238,0.2)]">
                        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                    </div>
                    <div>
                        <h2 className="text-xl font-bold text-cyan-400 tracking-wider font-mono drop-shadow-sm">
                            AUTHORIZATION REQUIRED
                        </h2>
                        <p className="text-xs text-cyan-600 font-mono tracking-widest uppercase">
                            AI Logic Core Request
                        </p>
                    </div>
                </div>

                <div className="mb-8 space-y-4 relative z-10">
                    <p className="text-gray-300 leading-relaxed text-sm">
                        The system is requesting permission to execute an autonomous function. Please review the parameters below.
                    </p>

                    <div className="space-y-2">
                        <div className="bg-cyan-950/30 border border-cyan-800/50 rounded-xl overflow-hidden">
                            <div className="bg-cyan-900/40 px-4 py-2 border-b border-cyan-800/50 flex justify-between items-center">
                                <span className="text-xs text-cyan-400 font-bold uppercase tracking-wider">Function</span>
                                <span className="text-xs text-white/50 font-mono">system.call</span>
                            </div>
                            <div className="p-4">
                                <div className="text-white font-mono text-lg font-medium">{request.tool}</div>
                            </div>
                        </div>

                        <div className="bg-cyan-950/30 border border-cyan-800/50 rounded-xl overflow-hidden">
                            <div className="bg-cyan-900/40 px-4 py-2 border-b border-cyan-800/50 flex justify-between items-center">
                                <span className="text-xs text-cyan-400 font-bold uppercase tracking-wider">Parameters</span>
                                <span className="text-xs text-white/50 font-mono">json.payload</span>
                            </div>
                            <div className="p-4 bg-black/20">
                                <pre className="text-xs text-gray-300 font-mono overflow-x-auto whitespace-pre-wrap leading-relaxed">
                                    {JSON.stringify(request.args, null, 2)}
                                </pre>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="flex gap-4 relative z-10">
                    <button
                        onClick={handleDeny}
                        className="flex-1 px-4 py-3.5 rounded-xl border border-red-500/30 bg-red-950/40 text-red-400 hover:bg-red-900/60 hover:border-red-500 hover:text-red-300 transition-all duration-200 font-bold tracking-wider uppercase text-xs"
                    >
                        Deny Request
                    </button>
                    <button
                        onClick={handleConfirm}
                        className="flex-1 px-4 py-3.5 rounded-xl border border-cyan-500/30 bg-cyan-950/40 text-cyan-400 hover:bg-cyan-900/60 hover:border-cyan-400 hover:text-cyan-300 transition-all duration-200 font-bold tracking-wider uppercase text-xs shadow-[0_0_20px_rgba(34,211,238,0.1)] hover:shadow-[0_0_30px_rgba(34,211,238,0.25)] relative overflow-hidden group"
                    >
                        <span className="relative z-10">Authorize Execution</span>
                        <div className="absolute inset-0 bg-cyan-400/10 translate-y-full group-hover:translate-y-0 transition-transform duration-300"></div>
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ConfirmationPopup;
