/**
 * Central socket -> store bridge.
 * Called once at app startup from main.jsx. Returns cleanup function.
 * Replaces the 300-line useEffect in the old App.jsx.
 */
import socket from './socket';
import { createSubscriptions } from './subscriptions';
import { registerConversationEvents } from './events/conversation';
import { registerCreativeEvents } from './events/creative';
import { registerDevicesEvents } from './events/devices';
import { registerRemindersEvents } from './events/reminders';
import useStore from '../store';
import { conversationForProject } from '../store/chatSlice';

const getConnectionStatus = ({ backendConnected, aiConnected, aiConnecting, aiUnavailable }) => {
    if (!backendConnected) return 'Backend Disconnected';
    if (aiConnecting) return 'AI Connecting';
    if (aiConnected) return 'AI Connected';
    if (aiUnavailable) return 'AI Unavailable';
    return 'Backend Connected';
};

export function initSocketListeners() {
    const scope = createSubscriptions(socket);
    const onSocket = scope.on;
    const unsubs = [];
    const s = useStore.getState;
    const deliveredReminderIds = new Set();
    const resumeConversation = (force = false) => {
        if (!force && (s().conversationRestoring || s().textProcessing)) return;
        useStore.setState({ conversationRestoring: true });
        socket.emit('resume_conversation', { conversation_id: s().conversationId });
    };
    // --- Connection ---
    unsubs.push(onSocket('connect', () => {
        const current = s();
        useStore.setState({
            backendConnected: true,
            localDevicesReady: true,
            status: getConnectionStatus({
                backendConnected: true,
                aiConnected: current.aiConnected,
                aiConnecting: current.aiConnecting,
                aiUnavailable: current.aiUnavailable,
            }),
        });
        socket.emit('get_settings');
        resumeConversation();
    }));

    unsubs.push(onSocket('disconnect', () => {
        useStore.setState({
            status: 'Backend Disconnected',
            confirmationRequest: null, pendingTextRequest: null,
            activity: s().activity.filter(item => !['approval', 'submitting'].includes(item.state)),
            backendConnected: false,
            aiConnected: false,
            aiConnecting: false,
            aiUnavailable: false,
            localDevicesReady: false,
            isMuted: true,
            listeningState: 'idle',
            textProcessing: false,
            conversationRestoring: false,
        });
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
            useStore.setState({
                status: 'AI Connected',
                aiConnected: true,
                aiConnecting: false,
                aiUnavailable: false,
            });
        } else if (data.msg === 'INARA Stopped') {
            useStore.setState({
                status: 'Backend Connected',
                aiConnected: false,
                aiConnecting: false,
                aiUnavailable: false,
                isMuted: false,
                listeningState: 'idle',
            });
        } else if (data.msg === 'Audio Paused') {
            useStore.setState({ isMuted: true });
        } else if (data.msg === 'Audio Resumed') {
            useStore.setState({ isMuted: false });
        } else if (data.msg === 'AI Unavailable') {
            useStore.setState({
                status: 'AI Unavailable',
                aiConnected: false,
                aiConnecting: false,
                aiUnavailable: true,
                isMuted: true,
                listeningState: 'idle',
            });
        }
    }));

    unsubs.push(onSocket('error', (data) => {
        if (data.conversation_id && data.conversation_id !== s().conversationId) return;
        if (data.project && data.project !== s().currentProject) return;
        s().addMessage('System', `Error: ${data.msg}`);
        if (data.msg?.startsWith('AI unavailable:')) {
            useStore.setState({
                status: 'AI Unavailable',
                aiConnected: false,
                aiConnecting: false,
                aiUnavailable: true,
                isMuted: true,
                listeningState: 'idle',
            });
        }
    }));

    // --- Audio ---
    unsubs.push(onSocket('audio_data', (data) => {
        useStore.setState({ aiAudioData: data.data });
    }));

    // --- Auth ---
    unsubs.push(onSocket('auth_status', (data) => {
        const unlocked = data.authenticated && !s().isAuthenticated;
        useStore.setState({ isAuthenticated: data.authenticated });
        if (!data.authenticated) {
            useStore.setState({ isLockScreenVisible: true });
        } else if (unlocked && s().backendConnected) {
            resumeConversation();
            socket.emit('get_reminders');
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

    // --- Tool Confirmation ---
    unsubs.push(onSocket('tool_confirmation_request', (data) => {
        useStore.setState({ confirmationRequest: data });
    }));

    const dependencies = { onSocket, socket, store: useStore, unsubs, deliveredReminderIds, resumeConversation, conversationForProject };
    registerConversationEvents(dependencies);
    registerCreativeEvents(dependencies);
    registerDevicesEvents(dependencies);
    registerRemindersEvents(dependencies);

    // Return cleanup
    return () => {
        scope.dispose();
    };
}
