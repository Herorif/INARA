import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, Play, Square } from 'lucide-react';
import {
  PREVIEW_NO_KEY, PreviewPlayer, SUGGESTED_VOICES, VOICE_MODES, modeHelp, voiceChoice, voiceGroups,
} from './voiceSettingsModel';
import SegmentedControl from './SegmentedControl';
import OverlaySettings from './OverlaySettings';
import MicrophoneSettings from './MicrophoneSettings';
import TrayVoiceDevices from './TrayVoiceDevices';
import { useAudioDeviceReport, useBrowserDevices } from './useAudioDevices';
import WakeWordSettings from './WakeWordSettings';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const IDLE = { playing: null, loading: null, error: null };

const ModeControl = ({ value, onChange }) =>
  <SegmentedControl name="voice-mode" options={VOICE_MODES} value={value} onChange={onChange} aria-label="Default voice mode" />;

function VoiceRow({ voice, selected, preview, previewAvailable, onChoose, onPreview }) {
  const playing = preview.playing === voice.name;
  const loading = preview.loading === voice.name;
  const Icon = loading ? Loader2 : playing ? Square : Play;
  return <li className="flex items-center gap-3 px-3 py-2" data-voice={voice.name}>
    <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
      <input type="radio" name="voice-name" value={voice.name} checked={selected} onChange={() => onChoose(voice.name)}
        className="h-3.5 w-3.5 shrink-0 cursor-pointer accent-[var(--accent)]" />
      <span className="min-w-0">
        <span className="text-sm text-ink-1">{voice.name}</span>
        {voice.isDefault && <span className="ml-2 text-[0.6875rem] text-ink-2">Default</span>}
        <span className="block text-[0.75rem] leading-snug text-ink-2">{voice.descriptor}</span>
      </span>
    </label>
    <button type="button" className="btn btn--ghost btn--icon btn--sm" aria-label={`Preview ${voice.name}`} aria-pressed={playing}
      title={previewAvailable ? undefined : PREVIEW_NO_KEY} disabled={!previewAvailable} onClick={() => onPreview(voice.name)}>
      <Icon size={14} aria-hidden="true" className={loading ? 'animate-spin' : undefined} />
    </button>
  </li>;
}

/**
 * VOICE group of "AI and assistant". `voice` is the saved settings.voice; `patch(settings)`
 * saves through update_settings and resolves to '' or a failure message. `previewAvailable`
 * is true with a Gemini key, false without one, and null while key status is loading.
 */
export default function VoiceSettings({ voice, client, previewAvailable, patch }) {
  const choice = voiceChoice(voice);
  const groups = useMemo(voiceGroups, []);
  const [showAll, setShowAll] = useState(false);
  const [preview, setPreview] = useState(IDLE);
  const [failure, setFailure] = useState('');
  const player = useMemo(() => new PreviewPlayer({ fetch: (name) => client.voicePreview(name), onChange: setPreview }), [client]);
  // One device list for the Microphone and the tray speaker; a plugged or unplugged device reloads it.
  const { report, loadError, reload } = useAudioDeviceReport();
  const devices = useBrowserDevices(reload);

  useEffect(() => () => player.close(), [player]);
  useEffect(() => { if (previewAvailable !== true) player.stop(); }, [previewAvailable, player]);
  // A saved voice outside the suggestions stays visible.
  useEffect(() => { if (!SUGGESTED_VOICES.includes(choice.name)) setShowAll(true); }, [choice.name]);

  const save = async (next) => setFailure(await patch({ voice: next }));
  const chooseVoice = (name) => { if (name !== choice.name) save({ name }); };
  const chooseMode = (mode) => { if (mode !== choice.mode) save({ mode }); };

  const rows = (list) => <ul className="divide-y divide-line rounded-md border border-line bg-panel">
    {list.map((item) =>
      <VoiceRow key={item.name} voice={item} selected={choice.name === item.name} preview={preview}
        previewAvailable={previewAvailable === true} onChoose={chooseVoice} onPreview={(name) => player.toggle(name)} />
    )}
  </ul>;

  return <div className="flex flex-col gap-2" data-voice-settings>
    <h4 className="hud-label">Voice</h4>
    <div className={ROW}>
      <span id="voice-name-label" className="text-sm text-ink-1">Voice</span>
      {previewAvailable === false && <p className={HELP} data-preview-note>{PREVIEW_NO_KEY}</p>}
      <div role="radiogroup" aria-labelledby="voice-name-label" className="flex flex-col gap-2">
        <h5 className="hud-label">Suggested</h5>
        {rows(groups.suggested)}
        {showAll && <>
          <h5 className="hud-label">Other voices</h5>
          {rows(groups.other)}
        </>}
      </div>
      <div>
        <button type="button" className="btn btn--ghost btn--sm" aria-expanded={showAll} onClick={() => setShowAll((value) => !value)}>
          {showAll ? 'Show fewer voices' : 'Show all voices'}
        </button>
      </div>
      <p aria-live="polite" className="min-h-0 text-[0.75rem] leading-snug text-danger">
        {preview.error ? `${preview.error.name}: ${preview.error.message}` : ''}
      </p>
    </div>
    <div className={ROW}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <span className="text-sm text-ink-1">Default voice mode</span>
        <ModeControl value={choice.mode} onChange={chooseMode} />
      </div>
      <p className={HELP} data-mode-help>{modeHelp(choice.mode)}</p>
    </div>
    <WakeWordSettings voice={voice} patch={patch} />
    <OverlaySettings voice={voice} patch={patch} />
    <MicrophoneSettings voice={voice} patch={patch} report={report} loadError={loadError} devices={devices} />
    <TrayVoiceDevices voice={voice} patch={patch} report={report} />
    <p aria-live="polite" className="min-h-0 text-[0.75rem] leading-snug text-danger">{failure}</p>
  </div>;
}
