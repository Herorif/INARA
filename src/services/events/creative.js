/** Scoped creative socket/store registrations. No connection ownership. */
export function registerCreativeEvents({ onSocket, socket, store: useStore, unsubs, deliveredReminderIds }) {
    const s = useStore.getState;
    for (const kind of ['cad', 'image']) unsubs.push(onSocket(`${kind}_job`, job => s().recordActivity(kind, job)));
    // --- CAD ---
    unsubs.push(onSocket('cad_data', (data) => {
        useStore.setState({ cadData: data, cadThoughts: '', showCadWindow: true });
    }));

    unsubs.push(onSocket('cad_status', (data) => {
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

}
