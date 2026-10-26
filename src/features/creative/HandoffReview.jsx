import React, {useEffect, useRef, useState} from 'react';
import {ArrowRight, Link2} from 'lucide-react';
import useStore from '../../store';
import socket from '../../services/socket';
import {createHandoffClient} from '../../transport/handoffClient.ts';
import './handoff.css';

export default function HandoffReview({destination, project, version, disabled, onApply}) {
  const pending = useStore(state => state.studioHandoff);
  const connected = useStore(state => state.backendConnected);
  const [draft,setDraft] = useState(null), [error,setError] = useState('');
  const captured = useRef(null);
  const selection = pending?.project === project && pending?.destination === destination ? pending : null;
  const discard = () => {if (useStore.getState().studioHandoff?.id === selection?.id) useStore.setState({studioHandoff:null});};
  useEffect(() => {
    setDraft(null);setError('');
    if (!selection || !connected || disabled) return;
    let live = true;
    const client = createHandoffClient(socket, project);
    captured.current = version.current;
    const {source_kind,source_request_id,source_fingerprint,destination:target} = selection;
    client.prepare({source_kind,source_request_id,source_fingerprint,destination:target}).then(value => {
      if (live) setDraft(value);
    }).catch(failure => {if(live)setError(failure.message);});
    return () => {live=false;client.dispose();};
  }, [selection?.id, connected, project, disabled]);
  useEffect(() => () => {
    if (selection && useStore.getState().studioHandoff?.id === selection.id) useStore.setState({studioHandoff:null});
  }, [selection?.id]);
  if (!selection) return null;
  const stale = draft && captured.current !== version.current;
  return <section className="creative-handoff hud-panel" aria-label="Creative handoff review">
    <span className="hud-label"><Link2 size={14} aria-hidden="true"/> Reference / review before applying</span>
    <h3>Review recipe handoff</h3>
    <div className="handoff-route"><span>{selection.source_kind === 'cad' ? '3D recipe' : 'Image recipe'}</span><ArrowRight size={16} aria-hidden="true"/><span>{destination === 'cad' ? '3D blueprint brief' : 'Image concept brief'}</span></div>
    <p>Recipe text only. No image pixels, camera content or model analysis are included. Applying changes your brief; generation stays a separate action.</p>
    {error ? <p className="handoff-error" role="alert">{error}</p> : !draft ? <p role="status">{connected ? 'Checking the saved source…' : 'Connection interrupted. Select the reference again after reconnecting.'}</p> : <>
      <strong>{draft.source_name}</strong><small>Source revision / <span className="handoff-id">{draft.reference.source_request_id}</span></small>
      <pre>{draft.prompt}</pre>
      {stale && <p className="handoff-error" role="alert">Your draft changed during review. Discard this handoff and select the reference again.</p>}
    </>}
    <div className="handoff-actions"><button type="button" className="btn btn--primary btn--sm" disabled={!connected || disabled || !draft || !!error || stale} onClick={() => {
      if (captured.current !== version.current || useStore.getState().currentProject !== project) return;
      onApply(draft);discard();
    }}>Apply brief to draft</button><button type="button" className="btn btn--ghost btn--sm" onClick={discard}>Discard handoff</button></div>
  </section>;
}

export function ReferenceNotice({reference, onClear, disabled}) {
  if (!reference) return null;
  return <section className="creative-reference hud-panel" aria-label="Draft source reference"><Link2 size={16} aria-hidden="true"/><div><strong>Recipe reference attached</strong><small>{reference.source_kind} / <span className="handoff-id">{reference.source_request_id}</span></small><p>This provenance is checked again before planning or building.</p></div><button type="button" className="btn btn--secondary btn--sm" disabled={disabled} onClick={onClear}>Detach reference</button></section>;
}
