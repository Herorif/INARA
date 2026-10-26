import React, { useEffect, useRef, useState } from 'react';
import { User } from 'lucide-react';
import useStore from '../store';
import socket from '../services/socket';

// Keep the recognised state readable before the lock fades (the previous screen held it for 2s).
const RECOGNIZED_HOLD_MS = 2000;
// Matches --dur-base, the opacity transition on .auth-lock.
const FADE_MS = 180;
const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

const AuthLock = () => {
    const setIsAuthenticated = useStore(s => s.setIsAuthenticated);
    const [frameSrc, setFrameSrc] = useState(null);
    const [status, setStatus] = useState('looking');
    const [leaving, setLeaving] = useState(false);
    const unlocking = useRef(false);
    const timers = useRef([]);

    useEffect(() => {
        const later = (callback, delay) => { timers.current.push(setTimeout(callback, delay)); };
        const handleAuthStatus = (data) => {
            if (unlocking.current) return;
            if (!data?.authenticated) { setStatus('looking'); return; }
            unlocking.current = true;
            setStatus('recognized');
            later(() => {
                setLeaving(true);
                // Visibility follows state, not transitionend: the reduced-motion kill switch
                // removes the transition, so that event would never fire.
                later(() => {
                    setIsAuthenticated(true);
                    useStore.setState({ isLockScreenVisible: false });
                }, reducedMotion() ? 0 : FADE_MS);
            }, RECOGNIZED_HOLD_MS);
        };
        const handleAuthFrame = (data) => setFrameSrc(`data:image/jpeg;base64,${data.image}`);

        socket.on('auth_status', handleAuthStatus);
        socket.on('auth_frame', handleAuthFrame);
        return () => {
            socket.off('auth_status', handleAuthStatus);
            socket.off('auth_frame', handleAuthFrame);
            timers.current.forEach(clearTimeout);
            timers.current = [];
        };
    }, [setIsAuthenticated]);

    // "Face not recognized. Try again." needs a rejection signal; the core only reports
    // authenticated true/false, and false is also its idle "still locked" state.
    const message = status === 'recognized' ? 'Face recognized' : status === 'rejected' ? 'Face not recognized. Try again.' : 'Looking for your face…';

    return (
        <div className={`auth-lock ${leaving ? 'is-leaving' : ''}`} role="dialog" aria-modal="true" aria-labelledby="auth-lock-title">
            <div className="auth-lock__content">
                <span className="monogram monogram--lg" aria-hidden="true">I</span>
                <h1 id="auth-lock-title">Locked</h1>
                <p className="auth-lock__status" role="status" data-state={status}>{message}</p>
                <div className="auth-lock__camera hud-panel">
                    {frameSrc ? <img src={frameSrc} alt="Camera preview for face unlock" /> : <User size={40} strokeWidth={1.25} aria-hidden="true" />}
                </div>
            </div>
        </div>
    );
};

export default AuthLock;
