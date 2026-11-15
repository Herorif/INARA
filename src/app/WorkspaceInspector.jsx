import React from 'react';
import { X } from 'lucide-react';
import PresenceRing, { presenceLabel } from './PresenceRing';
import { voicePresence } from '../features/voice/status.js';
import HudLabel from '../shared/ui/HudLabel';
import Kbd from '../shared/ui/Kbd';
import SystemsRail from './SystemsRail';

/**
 * The context inspector: the presence panel, then the Systems rail (SystemsRail.jsx).
 * `showPresence={false}` hides the presence panel (the Assistant view shows its own speaking core).
 */
export default function WorkspaceInspector({ connected, processing, voice, gaming, resource, memory, onOpen, onClose, showPresence = true }) {
  const presence = voicePresence({ connected, processing, voice });
  return <aside id="workspace-inspector" className="workspace-inspector" aria-label="Workspace context">
    <div className="inspector-heading"><HudLabel>CONTEXT</HudLabel><button type="button" className="btn btn--ghost btn--icon btn--sm" aria-label="Close context inspector" onClick={onClose}><X size={14} aria-hidden="true"/></button></div>
    {showPresence && <section className="inspector-panel inspector-presence hud-panel hud-frame" aria-label="Assistant presence">
      <PresenceRing size={64} state={presence} level={voice?.level ?? 0} lowPower={gaming}/>
      <div className="inspector-presence__copy"><strong className="presence-status hud-label" data-presence={presence}>{presenceLabel(presence)}</strong><span className="inspector-presence__hint"><Kbd>Ctrl Shift Space</Kbd> to&nbsp;talk</span></div>
    </section>}
    <SystemsRail connected={connected} gaming={gaming} voice={voice} resource={resource} memory={memory} onOpen={onOpen}/>
  </aside>;
}
