import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import useStore from '../store';
import Conversation from './Conversation';
import LiveDesignPanel from '../features/liveDesign/LiveDesignPanel';
import HudFrame from '../shared/ui/HudFrame';
import Materialise from '../shared/motion/MaterialisePresence';
import { WIDE_MIN_PX } from '../features/liveDesign/model.js';

/**
 * The Assistant page: the conversation, and beside it the owner's live design while one exists
 * (docs/LIVE_DESIGN.md, "Workspace panel"). A canvas WIDE_MIN_PX or wider shows both side by
 * side; a narrower one switches between them, and turns to the design whenever a new one
 * starts. Conversation stays mounted in the same place throughout; while its tab is hidden it
 * tells the core its speaking core isn't shown. The design panel materialises in a HUD frame
 * (src/shared/motion/) and is kept on screen, not visible to the store, while it leaves.
 */
export default function AssistantView({ onOpen, gaming = false }) {
  const live = useStore(state => state.liveDesign);
  // The last design stays mounted until its panel has finished leaving.
  const [held, setHeld] = useState(live);
  if (live && live !== held) setHeld(live);
  const design = live || held;
  const leaving = !live && !!held;
  const root = useRef(null);
  const [wide, setWide] = useState(true);
  const [tab, setTab] = useState('design');
  const designId = design?.id || null;
  const shown = useRef(designId);

  useLayoutEffect(() => {
    const canvas = root.current?.parentElement;
    if (!canvas) return undefined;
    const measure = () => setWide(canvas.clientWidth >= WIDE_MIN_PX);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (designId && designId !== shown.current) setTab('design');
    shown.current = designId;
  }, [designId]);

  const split = !!design && wide;
  const tabbed = !!design && !wide;
  const layout = split ? 'split' : tabbed ? 'tabbed' : 'single';
  const designHidden = tabbed && tab !== 'design';
  return <div ref={root} className="assistant-view" data-layout={layout} data-tab={tabbed ? tab : undefined}>
    {tabbed && <div className="assistant-view__switch" role="group" aria-label="Assistant view">
      {[['conversation', 'Conversation'], ['design', 'Live design']].map(([key, label]) => <button type="button" key={key} className="assistant-view__segment" aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}
    </div>}
    <div className="assistant-view__body">
      <div className="assistant-view__pane assistant-view__pane--conversation" hidden={tabbed && tab !== 'conversation'}>
        <Conversation onOpen={onOpen} gaming={gaming} hidden={tabbed && tab !== 'conversation'} />
      </div>
      {design && <div className="assistant-view__pane assistant-view__pane--design" hidden={designHidden}>
        {/* A hidden pane has nothing to animate: it comes and goes at once, like gaming mode. */}
        <Materialise show={!leaving} gaming={gaming || designHidden} className="assistant-view__design" onExitComplete={() => setHeld(null)}>
          <HudFrame index="02" title="Design" className="assistant-view__design-frame">
            <LiveDesignPanel design={design} visible={!leaving && (split || tab === 'design')} gaming={gaming} onOpen={onOpen} />
          </HudFrame>
        </Materialise>
      </div>}
    </div>
  </div>;
}
