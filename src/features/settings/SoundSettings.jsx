import React, { useEffect, useState } from 'react';
import { Play } from 'lucide-react';
import { emitSocket } from '../../services/socket';
import { playCue } from '../../services/sound/uiSounds.js';
import Switch from './Switch';
import {
  HEADING, SAMPLE_LABEL, SOUNDS_HELP, SOUNDS_LABEL, THINKING_HELP, THINKING_LABEL, VOLUME_LABEL,
  percentVolume, soundChoice, switchPatch, volumePatch, volumePercent,
} from './soundSettingsModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const LINE = 'flex flex-wrap items-center justify-between gap-x-3 gap-y-2';

/**
 * Preferences > Sound (S13a, docs/SOUND.md). `sound` is the saved settings.sound; the controls
 * save through update_settings and move when the core echoes the settings. The slider keeps a
 * draft while it moves and saves once it is let go, so dragging does not write the file each step.
 */
export default function SoundSettings({ sound }) {
  const choice = soundChoice(sound);
  const saved = volumePercent(choice.volume);
  const [draft, setDraft] = useState(saved);
  useEffect(() => { setDraft(saved); }, [saved]);

  const send = (patch) => { if (patch) emitSocket('update_settings', patch); };
  const commit = () => send(volumePatch(choice, draft));
  const sample = () => playCue('confirm', { sample: true, volume: percentVolume(draft) });

  return <section className="flex flex-col gap-2" data-sound-settings>
    <h3 className="hud-label">{HEADING}</h3>
    <div className={ROW}>
      <div className={LINE}>
        <span className="text-sm text-ink-1">{SOUNDS_LABEL}</span>
        <Switch checked={choice.enabled} label={SOUNDS_LABEL} onClick={() => send(switchPatch(choice, 'enabled', !choice.enabled))} />
      </div>
      <p className={HELP}>{SOUNDS_HELP}</p>
      <div className="flex items-center justify-between gap-3">
        <label htmlFor="settings-sound-volume" className="text-[0.75rem] text-ink-2">{VOLUME_LABEL}</label>
        <span className="font-mono text-[0.75rem] text-ink-2" aria-hidden="true">{`${draft}%`}</span>
      </div>
      <input id="settings-sound-volume" type="range" min="0" max="100" step="1" value={draft} disabled={!choice.enabled}
        aria-valuetext={`${draft}%`}
        onChange={(event) => setDraft(Number(event.target.value))}
        onPointerUp={commit} onKeyUp={commit} onBlur={commit}
        className="w-full cursor-pointer accent-accent disabled:cursor-not-allowed disabled:opacity-50" />
      <div>
        <button type="button" className="btn btn--secondary btn--sm" disabled={!choice.enabled} onClick={sample}>
          <Play size={14} aria-hidden="true" />
          <span>{SAMPLE_LABEL}</span>
        </button>
      </div>
      <div className={LINE}>
        <span className="text-sm text-ink-1">{THINKING_LABEL}</span>
        <Switch checked={choice.thinking} label={THINKING_LABEL} onClick={() => send(switchPatch(choice, 'thinking', !choice.thinking))} />
      </div>
      <p className={HELP}>{THINKING_HELP}</p>
    </div>
  </section>;
}
