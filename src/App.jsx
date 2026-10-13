import React, { useEffect, useRef } from 'react';
import { Minus, Printer, Clock, X } from 'lucide-react';

import useStore from './store';
import socket, { emitSocket } from './services/socket';
import { useAudioVisualizer } from './hooks/useAudioVisualizer';
import { useVideoCapture } from './hooks/useVideoCapture';
import { useHandTracking } from './hooks/useHandTracking';

import Visualizer from './components/Visualizer';
import TopAudioBar from './components/TopAudioBar';
import CadWindow from './components/CadWindow';
import BrowserWindow from './components/BrowserWindow';
import ChatModule from './components/ChatModule';
import ToolsModule from './components/ToolsModule';
import ConfirmationPopup from './components/ConfirmationPopup';
import AuthLock from './components/AuthLock';
import KasaWindow from './components/KasaWindow';
import PrinterWindow from './components/PrinterWindow';
import PhoneWindow from './components/PhoneWindow';
import ReminderWindow from './components/ReminderWindow';
import DesktopWindow from './components/DesktopWindow';
import ReminderAlert from './components/ReminderAlert';
import SettingsWindow from './components/SettingsWindow';
import VisionWindow from './components/VisionWindow';
import DeviceWindow from './components/DeviceWindow';

function App() {
    // --- Store selectors ---
    const isLockScreenVisible = useStore(s => s.isLockScreenVisible);
    const backendConnected = useStore(s => s.backendConnected);
    const aiConnected = useStore(s => s.aiConnected);
    const aiConnecting = useStore(s => s.aiConnecting);
    const aiUnavailable = useStore(s => s.aiUnavailable);
    const localDevicesReady = useStore(s => s.localDevicesReady);
    const isMuted = useStore(s => s.isMuted);
    const currentProject = useStore(s => s.currentProject);

    const aiAudioData = useStore(s => s.aiAudioData);
    const isVideoOn = useStore(s => s.isVideoOn);
    const fps = useStore(s => s.fps);
    const isHandTrackingEnabled = useStore(s => s.isHandTrackingEnabled);
    const isPinching = useStore(s => s.isPinching);
    const cursorPos = useStore(s => s.cursorPos);
    const isCameraFlipped = useStore(s => s.isCameraFlipped);

    const showSettings = useStore(s => s.showSettings);
    const showCadWindow = useStore(s => s.showCadWindow);
    const showBrowserWindow = useStore(s => s.showBrowserWindow);
    const showKasaWindow = useStore(s => s.showKasaWindow);
    const showPrinterWindow = useStore(s => s.showPrinterWindow);
    const showPhoneWindow = useStore(s => s.showPhoneWindow);
    const showReminderWindow = useStore(s => s.showReminderWindow);
    const showDesktopWindow  = useStore(s => s.showDesktopWindow);
    const showVisionWindow   = useStore(s => s.showVisionWindow);
    const showDeviceWindow   = useStore(s => s.showDeviceWindow);
    const isModularMode = useStore(s => s.isModularMode);
    const activeDragElement = useStore(s => s.activeDragElement);
    const elementPositions = useStore(s => s.elementPositions);
    const elementSizes = useStore(s => s.elementSizes);
    const currentTime = useStore(s => s.currentTime);
    const printerCount = useStore(s => s.printerCount);
    const kasaDevices = useStore(s => s.kasaDevices);
    const getZIndex = useStore(s => s.getZIndex);
    const bringToFront = useStore(s => s.bringToFront);
    const setElementPositions = useStore(s => s.setElementPositions);
    const setElementSizes = useStore(s => s.setElementSizes);
    const setActiveDragElement = useStore(s => s.setActiveDragElement);

    // --- Hooks ---
    useAudioVisualizer();
    const { videoRef, canvasRef, isVideoOnRef, toggleVideo, processFrame } = useVideoCapture();
    useHandTracking({ videoRef, canvasRef, isVideoOnRef, processFrame });

    // Store the toggleVideo in store so ToolsModule can call it
    useEffect(() => {
        useStore.setState({ toggleVideo });
    }, [toggleVideo]);

    // --- Mouse drag refs ---
    const dragOffsetRef = useRef({ x: 0, y: 0 });
    const isDraggingRef = useRef(false);
    const activeDragElementRef = useRef(null);
    const elementPositionsRef = useRef(elementPositions);
    const isModularModeRef = useRef(isModularMode);

    useEffect(() => {
        elementPositionsRef.current = elementPositions;
        isModularModeRef.current = isModularMode;
    }, [elementPositions, isModularMode]);

    // --- Live clock ---
    useEffect(() => {
        const timer = setInterval(() => useStore.setState({ currentTime: new Date() }), 1000);
        return () => clearInterval(timer);
    }, []);

    // --- Centering logic ---
    useEffect(() => {
        const centerElements = () => {
            const width = window.innerWidth;
            const height = window.innerHeight;
            const toolsCenterY = height - 100;
            const gap = 20;
            let vizH = 400;
            let chatH = 250;
            const topBarHeight = 60;
            const totalNeeded = topBarHeight + vizH + gap + chatH + gap + 140;

            if (height < totalNeeded) {
                const available = height - topBarHeight - 140 - (gap * 2);
                vizH = available * 0.6;
                chatH = available * 0.4;
            }

            const vizY = topBarHeight + (vizH / 2);
            const chatY = topBarHeight + vizH + gap;

            setElementSizes(prev => ({
                ...prev,
                visualizer: { w: Math.min(600, width * 0.8), h: vizH },
                chat: { w: Math.min(600, width * 0.9), h: chatH }
            }));

            setElementPositions(prev => ({
                ...prev,
                visualizer: { x: width / 2, y: vizY },
                chat: { x: width / 2, y: chatY },
                tools: { x: width / 2, y: toolsCenterY }
            }));
        };

        centerElements();
        window.addEventListener('resize', centerElements);
        return () => window.removeEventListener('resize', centerElements);
    }, [setElementSizes, setElementPositions]);

    // --- Enumerate devices ---
    useEffect(() => {
        navigator.mediaDevices.enumerateDevices().then(devs => {
            const audioInputs = devs.filter(d => d.kind === 'audioinput');
            const audioOutputs = devs.filter(d => d.kind === 'audiooutput');
            const videoInputs = devs.filter(d => d.kind === 'videoinput');

            const state = useStore.getState();
            useStore.setState({ micDevices: audioInputs, speakerDevices: audioOutputs, webcamDevices: videoInputs });

            const savedMicId = localStorage.getItem('selectedMicId');
            if (savedMicId && audioInputs.some(d => d.deviceId === savedMicId)) {
                useStore.setState({ selectedMicId: savedMicId });
            } else if (audioInputs.length > 0) {
                useStore.setState({ selectedMicId: audioInputs[0].deviceId });
            }

            const savedSpeakerId = localStorage.getItem('selectedSpeakerId');
            if (savedSpeakerId && audioOutputs.some(d => d.deviceId === savedSpeakerId)) {
                useStore.setState({ selectedSpeakerId: savedSpeakerId });
            } else if (audioOutputs.length > 0) {
                useStore.setState({ selectedSpeakerId: audioOutputs[0].deviceId });
            }

            const savedWebcamId = localStorage.getItem('selectedWebcamId');
            if (savedWebcamId && videoInputs.some(d => d.deviceId === savedWebcamId)) {
                useStore.setState({ selectedWebcamId: savedWebcamId });
            } else if (videoInputs.length > 0) {
                useStore.setState({ selectedWebcamId: videoInputs[0].deviceId });
            }
        });
    }, []);

    // --- Initial socket check ---
    useEffect(() => {
        if (socket.connected) {
            useStore.setState({
                status: 'Backend Connected',
                backendConnected: true,
                localDevicesReady: true,
            });
            emitSocket('get_settings');
        }
    }, []);

    // --- Mouse drag handlers ---
    const handleMouseDown = (e, id) => {
        const fixedElements = ['visualizer', 'chat', 'video', 'tools'];
        if (fixedElements.includes(id)) return;

        bringToFront(id);

        const tagName = e.target.tagName.toLowerCase();
        if (['input', 'button', 'textarea', 'canvas'].includes(tagName) || e.target.closest('button')) return;

        const isDragHandle = e.target.closest('[data-drag-handle]');
        if (!isDragHandle && !isModularModeRef.current) return;

        const elPos = elementPositionsRef.current[id];
        if (!elPos) return;

        dragOffsetRef.current = { x: e.clientX - elPos.x, y: e.clientY - elPos.y };
        setActiveDragElement(id);
        activeDragElementRef.current = id;
        isDraggingRef.current = true;

        const handleMouseDrag = (e) => {
            if (!isDraggingRef.current || !activeDragElementRef.current) return;
            const rawNewX = e.clientX - dragOffsetRef.current.x;
            const rawNewY = e.clientY - dragOffsetRef.current.y;

            setElementPositions(prev => {
                const size = elementSizes[activeDragElementRef.current] || { w: 100, h: 100 };
                let newX = rawNewX, newY = rawNewY;
                const w = window.innerWidth, h = window.innerHeight;
                newX = Math.max(size.w / 2, Math.min(w - size.w / 2, newX));
                newY = Math.max(size.h / 2, Math.min(h - size.h / 2, newY));
                return { ...prev, [activeDragElementRef.current]: { x: newX, y: newY } };
            });
        };

        const handleMouseUp = () => {
            isDraggingRef.current = false;
            setActiveDragElement(null);
            activeDragElementRef.current = null;
            window.removeEventListener('mousemove', handleMouseDrag);
            window.removeEventListener('mouseup', handleMouseUp);
        };

        window.addEventListener('mousemove', handleMouseDrag);
        window.addEventListener('mouseup', handleMouseUp);
    };

    // --- Window controls ---
    const handleMinimize = () => window.electronAPI?.minimize();
    const handleMaximize = () => window.electronAPI?.maximize();
    const handleCloseRequest = () => {
        const closeWindow = () => window.electronAPI?.close();
        if (socket.connected) {
            emitSocket('shutdown', {});
            setTimeout(closeWindow, 500);
        } else {
            closeWindow();
        }
    };

    // --- Computed ---
    const audioAmp = aiAudioData.reduce((a, b) => a + b, 0) / aiAudioData.length / 255;

    // --- Render ---
    return (
        <div className="h-screen w-screen bg-black text-cyan-100 font-mono overflow-hidden flex flex-col relative selection:bg-cyan-900 selection:text-white">

            {isLockScreenVisible && <AuthLock />}

            {isVideoOn && isHandTrackingEnabled && (
                <div
                    className={`fixed w-6 h-6 border-2 rounded-full pointer-events-none z-[100] transition-transform duration-75 ${isPinching ? 'bg-cyan-400 border-cyan-400 scale-75 shadow-[0_0_15px_rgba(34,211,238,0.8)]' : 'border-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.3)]'}`}
                    style={{ left: cursorPos.x, top: cursorPos.y, transform: 'translate(-50%, -50%)' }}
                >
                    <div className="absolute top-1/2 left-1/2 w-1 h-1 bg-white rounded-full -translate-x-1/2 -translate-y-1/2" />
                </div>
            )}

            <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-gray-900 via-black to-black z-0 pointer-events-none" style={{ opacity: 0.6 }}></div>
            <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-20 z-0 pointer-events-none mix-blend-overlay"></div>
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-cyan-900/10 rounded-full blur-[120px] pointer-events-none" />

            {/* Top Bar */}
            <div className="z-50 flex items-center justify-between p-2 border-b border-cyan-500/20 bg-black/40 backdrop-blur-md select-none sticky top-0" style={{ WebkitAppRegion: 'drag' }}>
                <div className="flex items-center gap-4 pl-2">
                    <h1 className="text-xl font-bold tracking-[0.2em] text-cyan-400 drop-shadow-[0_0_10px_rgba(34,211,238,0.5)]">
                        I.N.A.R.A
                    </h1>
                    <div className="text-[10px] text-cyan-700 border border-cyan-900 px-1 rounded">V2.0.0</div>
                    <div className={`text-[10px] px-2 py-0.5 rounded border ml-2 ${backendConnected ? 'text-green-400 border-green-500/30 bg-green-500/10' : 'text-red-400 border-red-500/30 bg-red-500/10'}`}>
                        {backendConnected ? 'BACKEND CONNECTED' : 'BACKEND OFFLINE'}
                    </div>
                    <div className={`text-[10px] px-2 py-0.5 rounded border ${aiConnected
                        ? 'text-green-400 border-green-500/30 bg-green-500/10'
                        : aiConnecting
                            ? 'text-cyan-400 border-cyan-500/30 bg-cyan-500/10 animate-pulse'
                            : aiUnavailable
                                ? 'text-red-400 border-red-500/30 bg-red-500/10'
                                : 'text-gray-400 border-gray-500/20 bg-gray-500/10'}`}>
                        {aiConnected ? 'AI CONNECTED' : aiConnecting ? 'AI CONNECTING' : aiUnavailable ? 'AI UNAVAILABLE' : 'AI IDLE'}
                    </div>
                    <div className={`text-[10px] px-2 py-0.5 rounded border ${localDevicesReady ? 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10' : 'text-gray-400 border-gray-500/20 bg-gray-500/10'}`}>
                        {localDevicesReady ? 'LOCAL DEVICES READY' : 'LOCAL DEVICES OFFLINE'}
                    </div>
                    {isVideoOn && <div className="text-[10px] text-green-500 border border-green-900 px-1 rounded ml-2">FPS: {fps}</div>}
                    {printerCount > 0 && (
                        <div className="flex items-center gap-1.5 text-[10px] text-green-400 border border-green-500/30 bg-green-500/10 px-2 py-0.5 rounded ml-2">
                            <Printer size={10} className="text-green-400" />
                            <span>{printerCount} Printer{printerCount !== 1 ? 's' : ''}</span>
                        </div>
                    )}
                    {kasaDevices.length > 0 && (
                        <div className="flex items-center gap-1.5 text-[10px] text-yellow-400 border border-yellow-500/30 bg-yellow-500/10 px-2 py-0.5 rounded ml-2">
                            <span>&#x1F4A1;</span>
                            <span>{kasaDevices.length} Device{kasaDevices.length !== 1 ? 's' : ''}</span>
                        </div>
                    )}
                </div>

                <div className="flex-1 flex justify-center mx-4">
                    <TopAudioBar />
                </div>

                <div className="flex items-center gap-2 pr-2" style={{ WebkitAppRegion: 'no-drag' }}>
                    <div className="flex items-center gap-1.5 text-[11px] text-cyan-300/70 font-mono px-2">
                        <Clock size={12} className="text-cyan-500/50" />
                        <span>{currentTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                    <button onClick={handleMinimize} className="p-1 hover:bg-cyan-900/50 rounded text-cyan-500 transition-colors"><Minus size={18} /></button>
                    <button onClick={handleMaximize} className="p-1 hover:bg-cyan-900/50 rounded text-cyan-500 transition-colors">
                        <div className="w-[14px] h-[14px] border-2 border-current rounded-[2px]" />
                    </button>
                    <button onClick={handleCloseRequest} className="p-1 hover:bg-red-900/50 rounded text-red-500 transition-colors"><X size={18} /></button>
                </div>
            </div>

            {/* Main Content */}
            <div className="flex-1 relative z-10 flex flex-col items-center justify-center">
                {/* Visualizer */}
                <div id="visualizer"
                    className={`absolute flex items-center justify-center transition-all duration-200
                        backdrop-blur-xl bg-black/30 border border-white/10 shadow-2xl overflow-visible
                        ${isModularMode ? (activeDragElement === 'visualizer' ? 'ring-2 ring-green-500 bg-green-500/10' : 'ring-1 ring-yellow-500/30 bg-yellow-500/5') + ' rounded-2xl pointer-events-auto' : 'rounded-2xl pointer-events-none'}`}
                    style={{ left: elementPositions.visualizer.x, top: elementPositions.visualizer.y, transform: 'translate(-50%, -50%)', width: elementSizes.visualizer.w, height: elementSizes.visualizer.h }}
                    onMouseDown={(e) => handleMouseDown(e, 'visualizer')}
                >
                    <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-10 pointer-events-none mix-blend-overlay z-10"></div>
                    <div className="relative z-20">
                        <Visualizer audioData={aiAudioData} isListening={aiConnected && !isMuted} intensity={audioAmp} width={elementSizes.visualizer.w} height={elementSizes.visualizer.h} />
                    </div>
                    {isModularMode && <div className={`absolute top-2 right-2 text-xs font-bold tracking-widest z-20 ${activeDragElement === 'visualizer' ? 'text-green-500' : 'text-yellow-500/50'}`}>VISUALIZER</div>}
                </div>

                {/* Project Label */}
                <div className="absolute top-[70px] left-1/2 -translate-x-1/2 text-cyan-500 text-xs font-mono tracking-widest pointer-events-none z-50 bg-black/50 px-2 py-1 rounded backdrop-blur-sm border border-cyan-500/20">
                    PROJECT: {currentProject?.toUpperCase()}
                </div>

                {/* Video Feed */}
                <div id="video"
                    className={`fixed bottom-4 right-4 transition-all duration-200 ${isVideoOn ? 'opacity-100' : 'opacity-0 pointer-events-none'} backdrop-blur-md bg-black/40 border border-white/10 shadow-xl rounded-xl`}
                    style={{ zIndex: 20 }}
                >
                    <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-5 pointer-events-none mix-blend-overlay"></div>
                    <div className="relative border border-cyan-500/30 rounded-lg overflow-hidden shadow-[0_0_20px_rgba(6,182,212,0.1)] w-80 aspect-video bg-black/80">
                        <video ref={videoRef} autoPlay muted className="absolute inset-0 w-full h-full object-cover opacity-0" />
                        <div className="absolute top-2 left-2 text-[10px] text-cyan-400 bg-black/60 backdrop-blur px-2 py-0.5 rounded border border-cyan-500/20 z-10 font-bold tracking-wider">CAM_01</div>
                        <canvas ref={canvasRef} className="absolute inset-0 w-full h-full opacity-80" style={{ transform: isCameraFlipped ? 'scaleX(-1)' : 'none' }} />
                    </div>
                </div>

                {/* Settings */}
                {showSettings && <SettingsWindow onClose={() => useStore.setState({ showSettings: false })} />}

                {/* CAD Window */}
                {showCadWindow && (
                    <div id="cad"
                        className={`absolute flex flex-col transition-all duration-200 backdrop-blur-xl bg-black/40 border border-white/10 shadow-2xl overflow-hidden rounded-2xl ${activeDragElement === 'cad' ? 'ring-2 ring-green-500 bg-green-500/10' : ''}`}
                        style={{ left: elementPositions.cad?.x || window.innerWidth / 2, top: elementPositions.cad?.y || window.innerHeight / 2, transform: 'translate(-50%, -50%)', width: `${elementSizes.cad.w}px`, height: `${elementSizes.cad.h}px`, pointerEvents: 'auto', zIndex: getZIndex('cad') }}
                        onMouseDown={(e) => handleMouseDown(e, 'cad')}
                    >
                        <div data-drag-handle className="h-8 bg-gray-900/80 border-b border-cyan-500/20 flex items-center justify-between px-3 cursor-grab active:cursor-grabbing shrink-0">
                            <span className="text-xs font-bold tracking-widest text-cyan-500/70">CAD PROTOTYPE</span>
                            <button onClick={() => useStore.setState({ showCadWindow: false })} className="text-gray-400 hover:text-red-400 hover:bg-red-500/20 p-1 rounded transition-colors">&#x2715;</button>
                        </div>
                        <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-10 pointer-events-none mix-blend-overlay z-10"></div>
                        <div className="relative z-20 flex-1 min-h-0">
                            <CadWindow onClose={() => useStore.setState({ showCadWindow: false })} />
                        </div>
                    </div>
                )}

                {/* Browser Window */}
                {showBrowserWindow && (
                    <div id="browser"
                        className={`absolute flex flex-col transition-all duration-200 backdrop-blur-xl bg-black/40 border border-white/10 shadow-2xl overflow-hidden rounded-lg ${activeDragElement === 'browser' ? 'ring-2 ring-green-500 bg-green-500/10' : ''}`}
                        style={{ left: elementPositions.browser?.x || window.innerWidth / 2 - 200, top: elementPositions.browser?.y || window.innerHeight / 2, transform: 'translate(-50%, -50%)', width: `${elementSizes.browser.w}px`, height: `${elementSizes.browser.h}px`, pointerEvents: 'auto', zIndex: getZIndex('browser') }}
                        onMouseDown={(e) => handleMouseDown(e, 'browser')}
                    >
                        <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-10 pointer-events-none mix-blend-overlay z-10"></div>
                        <div className="relative z-20 w-full h-full">
                            <BrowserWindow onClose={() => useStore.setState({ showBrowserWindow: false })} />
                        </div>
                    </div>
                )}

                {/* Chat */}
                <ChatModule isModularMode={isModularMode} activeDragElement={activeDragElement} position={elementPositions.chat} width={elementSizes.chat.w} height={elementSizes.chat.h} onMouseDown={(e) => handleMouseDown(e, 'chat')} />

                {/* Tools */}
                <div className="z-20 flex justify-center pb-10 pointer-events-none">
                    <ToolsModule position={elementPositions.tools} onMouseDown={(e) => handleMouseDown(e, 'tools')} />
                </div>

                {/* Kasa */}
                {showKasaWindow && (
                    <KasaWindow position={elementPositions.kasa} activeDragElement={activeDragElement} onClose={() => useStore.setState({ showKasaWindow: false })} onMouseDown={(e) => handleMouseDown(e, 'kasa')} zIndex={getZIndex('kasa')} />
                )}

                {/* Printer */}
                {showPrinterWindow && (
                    <PrinterWindow position={elementPositions.printer} onClose={() => useStore.setState({ showPrinterWindow: false })} onMouseDown={(e) => handleMouseDown(e, 'printer')} activeDragElement={activeDragElement} zIndex={getZIndex('printer')} />
                )}

                {/* Phone */}
                {showPhoneWindow && (
                    <PhoneWindow position={elementPositions.phone} onClose={() => useStore.setState({ showPhoneWindow: false })} onMouseDown={(e) => handleMouseDown(e, 'phone')} activeDragElement={activeDragElement} zIndex={getZIndex('phone')} />
                )}

                {/* Desktop */}
                {showDesktopWindow && (
                    <DesktopWindow position={elementPositions.desktop} onClose={() => useStore.setState({ showDesktopWindow: false })} onMouseDown={(e) => handleMouseDown(e, 'desktop')} activeDragElement={activeDragElement} zIndex={getZIndex('desktop')} />
                )}

                {/* Reminders */}
                {showReminderWindow && (
                    <ReminderWindow position={elementPositions.reminder} onClose={() => useStore.setState({ showReminderWindow: false })} onMouseDown={(e) => handleMouseDown(e, 'reminder')} activeDragElement={activeDragElement} zIndex={getZIndex('reminder')} />
                )}

                {/* Vision */}
                {showVisionWindow && (
                    <VisionWindow position={elementPositions.vision} onClose={() => useStore.setState({ showVisionWindow: false })} onMouseDown={(e) => handleMouseDown(e, 'vision')} activeDragElement={activeDragElement} zIndex={getZIndex('vision')} />
                )}

                {/* Devices */}
                {showDeviceWindow && (
                    <DeviceWindow position={elementPositions.device} onClose={() => useStore.setState({ showDeviceWindow: false })} onMouseDown={(e) => handleMouseDown(e, 'device')} activeDragElement={activeDragElement} zIndex={getZIndex('device')} />
                )}

                <ReminderAlert />
                <ConfirmationPopup />
            </div>
        </div>
    );
}

export default App;
