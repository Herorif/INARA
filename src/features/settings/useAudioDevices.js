import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import socket from '../../services/socket';
import { createAudioDevicesClient } from '../../transport/audioDevicesClient.ts';
import { rpcFailureMessage } from './aiSettingsModel';

const RELOAD_DELAY_MS = 800; // plugging a device in fires several devicechange events

/** The core's device list for Preferences > Voice: { report, loadError, reload }. */
export function useAudioDeviceReport() {
  const client = useMemo(() => createAudioDevicesClient(socket), []);
  const [report, setReport] = useState(null);
  const [loadError, setLoadError] = useState('');
  const latest = useRef(0);

  useEffect(() => () => client.dispose(), [client]);
  // Only the newest answer counts when reads overlap.
  const reload = useCallback(() => {
    const request = ++latest.current;
    client.list().then((next) => {
      if (request === latest.current) { setReport(next); setLoadError(''); }
    }).catch((error) => {
      if (request === latest.current) setLoadError(rpcFailureMessage(error));
    });
  }, [client]);
  useEffect(() => {
    reload();
    return client.on('connect', reload);
  }, [client, reload]);
  return { report, loadError, reload };
}

/**
 * The browser's devices (labels are Windows names), read again on every `devicechange`;
 * `onChange` runs once a burst of changes settles.
 */
export function useBrowserDevices(onChange) {
  const [devices, setDevices] = useState([]);
  const changed = useRef(onChange);
  changed.current = onChange;

  useEffect(() => {
    const media = globalThis.navigator?.mediaDevices;
    if (!media?.enumerateDevices) return undefined;
    let live = true, timer = null;
    const read = () => media.enumerateDevices().then((list) => { if (live) setDevices(list); }).catch(() => {});
    const onDeviceChange = () => {
      read();
      clearTimeout(timer);
      timer = setTimeout(() => changed.current?.(), RELOAD_DELAY_MS);
    };
    read();
    media.addEventListener?.('devicechange', onDeviceChange);
    return () => {
      live = false;
      clearTimeout(timer);
      media.removeEventListener?.('devicechange', onDeviceChange);
    };
  }, []);
  return devices;
}
