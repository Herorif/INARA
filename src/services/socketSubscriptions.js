/**
 * Central socket -> store bridge.
 * Called once at app startup from main.jsx. Returns cleanup function.
 * Replaces the 300-line useEffect in the old App.jsx.
 */
import socket, { onSocket } from './socket';
import useStore from '../store';

export function initSocketListeners() {
    const unsubs = [];
    const s = useStore.getState;

    // --- Connection ---
    unsubs.push(onSocket('connect', () => {
        useStore.setState({ status: 'Connected', socketConnected: true });
        socket.emit('get_settings');
    }));

    unsubs.push(onSocket('disconnect', () => {
        useStore.setState({ status: 'Disconnected', socketConnected: false });
    }));

    // --- Status ---
    unsubs.push(onSocket('status', (data) => {
        // Handle listening state changes from wake word system
        if (data.msg && data.msg.startsWith('listening_state:')) {
            const state = data.msg.split(':')[1];
            useStore.setState({ listeningState: state });
            return;
        }

        s().addMessage('System', data.msg);
        if (data.msg.includes('INARA Started')) {
            useStore.setState({ status: 'Model Connected' });
        } else if (data.msg === 'INARA Stopped') {
            useStore.setState({ status: 'Connected', listeningState: 'idle' });
        }
    }));

    unsubs.push(onSocket('error', (data) => {
        console.error('Socket Error:', data);
        s().addMessage('System', `Error: ${data.msg}`);
    }));

    // --- Audio ---
    unsubs.push(onSocket('audio_data', (data) => {
        useStore.setState({ aiAudioData: data.data });
    }));

    // --- Auth ---
    unsubs.push(onSocket('auth_status', (data) => {
        console.log('Auth Status:', data);
        useStore.setState({ isAuthenticated: data.authenticated });
        if (!data.authenticated) {
            useStore.setState({ isLockScreenVisible: true });
        }
    }));

    // --- Settings ---
    unsubs.push(onSocket('settings', (settings) => {
        console.log('[Settings] Received:', settings);
        if (settings && typeof settings.face_auth_enabled !== 'undefined') {
            s().setFaceAuthEnabled(settings.face_auth_enabled);
        }
        if (typeof settings.camera_flipped !== 'undefined') {
            useStore.setState({ isCameraFlipped: settings.camera_flipped });
        }
    }));

    // --- CAD ---
    unsubs.push(onSocket('cad_data', (data) => {
        console.log('Received CAD Data:', data);
        useStore.setState({ cadData: data, cadThoughts: '', showCadWindow: true });
    }));

    unsubs.push(onSocket('cad_status', (data) => {
        console.log('Received CAD Status:', data);
        if (data.attempt) {
            useStore.setState({
                cadRetryInfo: {
                    attempt: data.attempt,
                    maxAttempts: data.max_attempts || 3,
                    error: data.error,
                }
            });
        }
        if (data.status === 'generating' || data.status === 'retrying') {
            useStore.setState({ cadData: { format: 'loading' }, showCadWindow: true });
            if (data.status === 'generating' && data.attempt === 1) {
                useStore.setState({ cadThoughts: '' });
            }
        } else if (data.status === 'failed') {
            useStore.setState({ cadData: { format: 'loading' } });
        }
    }));

    unsubs.push(onSocket('cad_thought', (data) => {
        s().appendCadThought(data.text);
    }));

    // --- Browser ---
    unsubs.push(onSocket('browser_frame', (data) => {
        useStore.setState(state => ({
            browserData: {
                image: data.image,
                logs: [...state.browserData.logs, data.log].filter(l => l).slice(-50),
            },
            showBrowserWindow: true,
        }));
    }));

    // --- Transcription ---
    unsubs.push(onSocket('transcription', (data) => {
        s().appendTranscription(data.sender, data.text);
    }));

    // --- Tool Confirmation ---
    unsubs.push(onSocket('tool_confirmation_request', (data) => {
        console.log('Received Confirmation Request:', data);
        useStore.setState({ confirmationRequest: data });
    }));

    // --- Print Window Request ---
    unsubs.push(onSocket('request_print_window', () => {
        const clamp = s().clampToViewport;
        const clamped = clamp({ x: window.innerWidth / 2, y: window.innerHeight / 2 }, { w: 380, h: 380 });
        useStore.setState(state => ({
            showPrinterWindow: true,
            elementPositions: { ...state.elementPositions, printer: clamped },
        }));
    }));

    // --- Phone Calls ---
    unsubs.push(onSocket('call_incoming', (data) => {
        console.log('[CALL] Incoming:', data);
        useStore.setState({ incomingCall: data, showPhoneWindow: true });
    }));

    unsubs.push(onSocket('call_connected', (data) => {
        console.log('[CALL] Connected:', data);
        s().addActiveCall(data);
    }));

    unsubs.push(onSocket('call_ended', (data) => {
        console.log('[CALL] Ended:', data);
        s().removeActiveCall(data);
    }));

    unsubs.push(onSocket('call_status', (data) => {
        s().updateCallStatus(data);
    }));

    // --- Kasa ---
    unsubs.push(onSocket('kasa_devices', (devices) => {
        console.log('Kasa Devices:', devices);
        useStore.setState({ kasaDevices: devices });
    }));

    unsubs.push(onSocket('kasa_update', (data) => {
        s().updateKasaDevice(data);
    }));

    // --- Project ---
    unsubs.push(onSocket('project_update', (data) => {
        console.log('Project Update:', data.project);
        useStore.setState({ currentProject: data.project });
        s().addMessage('System', `Switched to project: ${data.project}`);
    }));

    // --- Printers ---
    unsubs.push(onSocket('printer_list', (list) => {
        console.log('[PRINTERS] Count:', list.length);
        s().setPrinterList(list);
    }));

    unsubs.push(onSocket('slicing_progress', (data) => {
        console.log('[SLICING] Progress:', data);
        useStore.setState({
            slicingStatus: {
                active: data.percent < 100,
                percent: data.percent,
                message: data.message,
            }
        });
    }));

    unsubs.push(onSocket('print_status_update', (data) => {
        console.log('[PRINT STATUS]', data);
        if (data.state && data.state.toLowerCase().includes('print')) {
            useStore.setState({
                activePrintStatus: {
                    printer: data.printer,
                    progress_percent: data.progress_percent,
                    time_elapsed: data.time_elapsed,
                    state: data.state,
                }
            });
        } else if (data.state && ['idle', 'standby', 'complete'].includes(data.state.toLowerCase())) {
            useStore.setState({ activePrintStatus: null });
        }
        // Also update printer in list
        s().updatePrinterStatus(data);
    }));

    // Return cleanup
    return () => {
        unsubs.forEach(fn => fn());
    };
}
