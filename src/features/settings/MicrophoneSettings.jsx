import React, { useRef, useState } from 'react';
import { devicePatch } from '../../transport/audioDevicesClient.ts';
import { automaticDeviceName } from '../voice/microphoneModel.js';
import { deviceNote, deviceOptions, savedDevice, selectedValue, selectionFor } from './trayVoiceDevicesModel';
import { BLOCKED_HELP, LEVEL_HELP, MICROPHONE_LABEL, meterTarget, usingText } from './microphoneSettingsModel';
import { useLevelMeter } from './useLevelMeter';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const SELECT = 'w-full rounded-md border border-line-strong bg-panel px-2 py-1.5 text-sm text-ink-1';

/**
 * The one Microphone for window voice, tray voice and "Hey Jarvis", with a live level bar.
 * `report` is the core's device list and `devices` the browser's (both loaded by
 * VoiceSettings, with `loadError`); `voice` is the saved settings.voice; `patch(settings)` saves through
 * update_settings and resolves to '' or a failure message.
 */
export default function MicrophoneSettings({ voice, patch, report, loadError, devices }) {
  const [failure, setFailure] = useState('');
  const rowRef = useRef(null), fillRef = useRef(null), meterRef = useRef(null);
  const entries = report?.inputs || [];
  const available = report?.available === true;
  const saved = savedDevice(voice, 'microphone');
  const using = usingText(saved, automaticDeviceName(entries, devices));
  const note = deviceNote(entries, saved, 'microphone', available);
  const { deviceId, restartKey } = meterTarget(saved, devices);
  const status = useLevelMeter({ deviceId, restartKey, rowRef, fillRef, meterRef });
  const blocked = status === 'blocked';

  const choose = async (value) => {
    const next = selectionFor(entries, saved, value);
    if (next === null) return;
    setFailure(await patch(devicePatch('microphone', next)));
  };

  return <div ref={rowRef} className={ROW} data-microphone-settings data-level={status}>
    <label htmlFor="voice-microphone" className="text-sm text-ink-1">{MICROPHONE_LABEL}</label>
    <select id="voice-microphone" className={SELECT} disabled={!available}
      value={selectedValue(entries, saved)} onChange={(event) => choose(event.target.value)}>
      {deviceOptions(entries, saved, 'microphone').map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
    {using && <p className={HELP} data-microphone-using>{using}</p>}
    {note && <p className={HELP} data-device-note="microphone">{note}</p>}
    {!blocked && <div ref={meterRef} role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={0}
      className="h-1 w-full bg-[var(--line)]" data-microphone-level>
      <div ref={fillRef} className="h-full w-0 rounded-full bg-[var(--accent)]" />
    </div>}
    <p className="text-[0.75rem] leading-relaxed text-ink-3" data-microphone-level-help>{blocked ? BLOCKED_HELP : LEVEL_HELP}</p>
    {report && !available && <p className={HELP} role="status" data-devices-unavailable>{report.message}</p>}
    <p aria-live="polite" className="min-h-0 text-[0.75rem] leading-snug text-danger">{loadError || failure}</p>
  </div>;
}
