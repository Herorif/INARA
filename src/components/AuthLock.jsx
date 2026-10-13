import React, { useEffect, useState } from 'react';
import { Lock, Unlock, User } from 'lucide-react';
import useStore from '../store';
import socket from '../services/socket';

const AuthLock = () => {
    const setIsAuthenticated = useStore(s => s.setIsAuthenticated);
    const [frameSrc, setFrameSrc] = useState(null);
    const [message, setMessage] = useState('Initializing Security...');
    const [isUnlocking, setIsUnlocking] = useState(false);

    useEffect(() => {
        const handleAuthStatus = (data) => {
            console.log('Auth Status:', data);
            if (data.authenticated && !isUnlocking) {
                setIsUnlocking(true);
                setMessage('Identity Verified. Access Granted.');
                setTimeout(() => {
                    setIsAuthenticated(true);
                }, 2000);
            } else if (!data.authenticated && !isUnlocking) {
                setMessage('Look at the camera to unlock.');
            }
        };

        const handleAuthFrame = (data) => {
            setFrameSrc(`data:image/jpeg;base64,${data.image}`);
        };

        socket.on('auth_status', handleAuthStatus);
        socket.on('auth_frame', handleAuthFrame);

        return () => {
            socket.off('auth_status', handleAuthStatus);
            socket.off('auth_frame', handleAuthFrame);
        };
    }, [setIsAuthenticated, isUnlocking]);

    const themeColor = isUnlocking ? 'text-green-500' : 'text-cyan-500';
    const borderColor = isUnlocking ? 'border-green-500' : 'border-cyan-500';
    const shadowColor = isUnlocking ? 'shadow-[0_0_50px_rgba(34,197,94,0.4)]' : 'shadow-[0_0_50px_rgba(34,211,238,0.2)]';
    const bgGradient = isUnlocking ? 'from-green-900/40 via-black to-black' : 'from-cyan-900/20 via-black to-black';

    return (
        <div className={`fixed inset-0 z-[9999] bg-black flex flex-col items-center justify-center font-mono select-none transition-all duration-[2000ms] ${isUnlocking ? 'opacity-0 scale-110 pointer-events-none' : 'opacity-100'}`}
            style={{ transitionDelay: '2000ms' }}
            onTransitionEnd={() => {
                if (isUnlocking) useStore.setState({ isLockScreenVisible: false });
            }}>

            <div className={`absolute inset-0 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] ${bgGradient} pointer-events-none transition-colors duration-[1500ms]`}></div>

            <div className={`relative flex flex-col items-center gap-6 p-10 border ${borderColor}/30 rounded-lg bg-black/80 backdrop-blur-xl ${shadowColor} transition-all duration-[1500ms]`}>
                <div className={`text-3xl font-bold tracking-[0.3em] uppercase drop-shadow-[0_0_10px_currentColor] flex items-center gap-4 ${themeColor} transition-colors duration-1000`}>
                    {isUnlocking ? <Unlock size={32} /> : <Lock size={32} />}
                    {isUnlocking ? 'SYSTEM UNLOCKED' : 'SYSTEM LOCKED'}
                </div>

                <div className={`relative w-64 h-64 border-2 ${borderColor}/50 rounded-lg overflow-hidden bg-gray-900 shadow-inner flex items-center justify-center transition-colors duration-500`}>
                    {frameSrc ? (
                        <img src={frameSrc} alt="Auth Camera"
                            className={`w-full h-full object-cover transform scale-x-[-1] transition-opacity duration-500 ${isUnlocking ? 'opacity-50 grayscale' : 'opacity-100'}`} />
                    ) : (
                        <div className={`animate-pulse ${isUnlocking ? 'text-green-800' : 'text-cyan-800'}`}>
                            <User size={64} />
                        </div>
                    )}
                    {!isUnlocking && (
                        <div className="absolute top-0 left-0 w-full h-1 bg-cyan-400/80 shadow-[0_0_15px_cyan] animate-[scan_2s_ease-in-out_infinite]"></div>
                    )}
                    {isUnlocking && (
                        <div className="absolute inset-0 flex items-center justify-center bg-green-500/20 animate-pulse">
                            <Unlock size={64} className="text-green-400 drop-shadow-[0_0_20px_rgba(74,222,128,0.8)]" />
                        </div>
                    )}
                </div>

                <div className={`text-sm tracking-widest ${isUnlocking ? 'text-green-300' : 'text-cyan-300'} animate-pulse transition-colors duration-500`}>
                    {message}
                </div>
            </div>

            <style>{`
                @keyframes scan {
                    0%, 100% { top: 0%; opacity: 0; }
                    50% { opacity: 1; }
                    100% { top: 100%; opacity: 0; }
                }
            `}</style>
        </div>
    );
};

export default AuthLock;
