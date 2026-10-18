/** Scoped devices socket/store registrations. No connection ownership. */
export function registerDevicesEvents({ onSocket, socket, store: useStore, unsubs, deliveredReminderIds }) {
    const s = useStore.getState;
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
        useStore.setState({ incomingCall: data, showPhoneWindow: true });
    }));

    unsubs.push(onSocket('call_connected', (data) => {
        s().addActiveCall(data);
    }));

    unsubs.push(onSocket('call_ended', (data) => {
        s().removeActiveCall(data);
    }));

    unsubs.push(onSocket('call_status', (data) => {
        s().updateCallStatus(data);
    }));

    // --- Kasa ---
    unsubs.push(onSocket('kasa_devices', (devices) => {
        useStore.setState({ kasaDevices: devices });
    }));

    unsubs.push(onSocket('kasa_update', (data) => {
        s().updateKasaDevice(data);
    }));

    // --- Printers ---
    unsubs.push(onSocket('printer_list', (list) => {
        s().setPrinterList(list);
    }));

    unsubs.push(onSocket('printer_system_status', (data) => {
        useStore.setState({ printerSystemStatus: data });
    }));

    unsubs.push(onSocket('slicing_progress', (data) => {
        useStore.setState({
            slicingStatus: {
                active: data.percent < 100,
                percent: data.percent,
                message: data.message,
            }
        });
    }));

    unsubs.push(onSocket('print_status_update', (data) => {
        if (data.state && data.state.toLowerCase().includes('print')) {
            useStore.setState({
                activePrintStatus: {
                    printer: data.printer,
                    progress_percent: data.progress_percent,
                    time_elapsed: data.time_elapsed,
                    state: data.state,
                }
            });
        } else if (data.state && ['idle', 'standby', 'complete', 'offline'].includes(data.state.toLowerCase())) {
            useStore.setState({ activePrintStatus: null });
        }
        // Also update printer in list
        s().updatePrinterStatus(data);
    }));

    // --- Vision ---
    unsubs.push(onSocket('vision_alert', (data) => {
        useStore.setState({ showVisionWindow: true });
        s().addVisionAlert(data);
    }));

    unsubs.push(onSocket('vision_description', (data) => {
        if (data.description) useStore.setState({ lastVisionDescription: data.description });
    }));

    unsubs.push(onSocket('vision_presence', (data) => {
        useStore.setState({ presenceDetected: data.present });
    }));

    // --- Unified Devices ---
    unsubs.push(onSocket('device_list', (data) => {
        if (data.devices) useStore.setState({ allDevices: data.devices });
    }));

    unsubs.push(onSocket('device_control', (data) => {
        if (data.device_id) {
            const updates = { lastAction: data.action };
            if (data.action === 'turn_on') updates.state = 'on';
            else if (data.action === 'turn_off') updates.state = 'off';
            s().updateDeviceState(data.device_id, updates);
        }
    }));

    unsubs.push(onSocket('vision_watches', (data) => {
        if (data.watches) useStore.setState({ activeWatches: data.watches });
    }));

    // --- Desktop ---
    unsubs.push(onSocket('desktop_system_info', (data) => {
        s().setSystemInfo(data);
        if (data.processes) s().setRunningApps(data.processes);
    }));

    unsubs.push(onSocket('desktop_screenshot', (data) => {
        if (data.data?.image || data.image) s().setLastScreenshot(data.data?.image || data.image);
    }));

}
