/**
 * Central socket -> store bridge.
 * Called once at app startup from main.jsx. Returns cleanup function.
 * Replaces the 300-line useEffect in the old App.jsx.
 */
import socket, { emitSocket } from './socket';
import { createSubscriptions } from './subscriptions';
import { registerConversationEvents } from './events/conversation';
import { registerCreativeEvents } from './events/creative';
import { registerDevicesEvents } from './events/devices';
import { registerRemindersEvents } from './events/reminders';
import { registerLocalVoiceEvents } from './events/localVoice';
import { registerLiveDesignEvents } from './events/liveDesign';
import { registerCallAlertEvents } from './events/callAlerts';
import { registerCalendarEvents } from './events/calendar';
import { registerBriefingEvents } from './events/briefing';
import { registerVisionCaptureEvents } from './events/visionCapture';
import useStore from '../store';
import { conversationForProject } from '../store/chatSlice';
import { defaultVoiceMode } from '../features/voice/defaultMode.js';
import { adoptLegacyMicrophone } from '../features/voice/legacyMicrophone.js';
import { savedDevice } from '../features/settings/trayVoiceDevicesModel.js';

/** Matches the core's ToolDispatcher approval timeout; the core rejects later answers. */
const APPROVAL_TIMEOUT_MS = 60_000;

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
        // A reply still being written will not finish: keep its text, marked stopped.
        s().stopReplies?.();
        useStore.setState({
            status: 'Backend Disconnected',
            confirmationRequest: null, confirmationQueue: [], pendingTextRequest: null,
            studioHandoff: null,
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
        if (data.msg.includes('JARVIS Started')) {
            useStore.setState({
                status: 'AI Connected',
                aiConnected: true,
                aiConnecting: false,
                aiUnavailable: false,
            });
        } else if (data.msg === 'JARVIS Stopped') {
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
        if (settings && settings.voice) useStore.setState({ voiceDefaultMode: defaultVoiceMode(settings) });
        if (settings && typeof settings === 'object') {
            const saved = savedDevice(settings.voice, 'microphone');
            useStore.setState({ voiceMicrophone: saved });
            adoptLegacyMicrophone({ socket, saved, emit: emitSocket });
        }
    }));

    // --- Tool Confirmation ---
    // Requests queue by id; each one leaves the queue when answered, closed or expired.
    const approvalTimers = new Map();
    const forgetApproval = id => { clearTimeout(approvalTimers.get(id)); approvalTimers.delete(id); };
    unsubs.push(onSocket('tool_confirmation_request', (data) => {
        if (!data?.id) return;
        forgetApproval(data.id);
        approvalTimers.set(data.id, setTimeout(() => {
            approvalTimers.delete(data.id);
            s().resolveConfirmation(data.id);
        }, APPROVAL_TIMEOUT_MS));
        s().enqueueConfirmation(data);
    }));

    unsubs.push(onSocket('task_queue_approval_closed', data => {
        s().confirmationQueue.filter(item => item.task_queue?.id === data.id).forEach(item => s().resolveConfirmation(item.id));
    }));

    // Other panels dismiss the visible request with `confirmationRequest: null`; treat that as
    // resolving exactly that id. A project switch drops every request from the old project.
    const stopApprovalSync = useStore.subscribe((state, previous) => {
        if (state.currentProject !== previous.currentProject && state.confirmationQueue.length) {
            useStore.setState({ confirmationQueue: [], confirmationRequest: null });
            return;
        }
        if (!state.confirmationRequest && previous.confirmationRequest && state.confirmationQueue.some(item => item.id === previous.confirmationRequest.id)) {
            s().resolveConfirmation(previous.confirmationRequest.id);
            return;
        }
        if (state.confirmationQueue !== previous.confirmationQueue) {
            const live = new Set(state.confirmationQueue.map(item => item.id));
            [...approvalTimers.keys()].filter(id => !live.has(id)).forEach(forgetApproval);
        }
    });

    const dependencies = { onSocket, socket, store: useStore, unsubs, deliveredReminderIds, resumeConversation, conversationForProject };
    registerConversationEvents(dependencies);
    registerCreativeEvents(dependencies);
    registerDevicesEvents(dependencies);
    registerRemindersEvents(dependencies);
    registerLocalVoiceEvents(dependencies);
    registerLiveDesignEvents(dependencies);
    registerCallAlertEvents(dependencies);
    registerCalendarEvents(dependencies);
    registerBriefingEvents(dependencies);
    registerVisionCaptureEvents(dependencies);

    // Return cleanup
    return () => {
        stopApprovalSync();
        approvalTimers.forEach(timer => clearTimeout(timer));
        approvalTimers.clear();
        scope.dispose();
    };
}
