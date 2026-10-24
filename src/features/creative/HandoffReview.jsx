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
  return <section className="creative-handoff" aria-label="Creative handoff review">
    <span className="eyebrow"><Link2 size={14}/> REFERENCE / REVIEW BEFORE APPLYING</span>
    <h3>A new direction, with a traceable beginning.</h3>
    <div className="handoff-route"><span>{selection.source_kind === 'cad' ? '3D recipe' : 'Image recipe'}</span><ArrowRight size={17}/><span>{destination === 'cad' ? '3D blueprint brief' : 'Image concept brief'}</span></div>
    <p>Recipe text only. No image pixels, camera content or AI analysis are included. Applying changes your brief; generation stays a separate action.</p>
    {error ? <p role="alert">{error}</p> : !draft ? <p role="status">{connected ? 'Checking the saved source…' : 'Connection interrupted. Select the reference again after reconnecting.'}</p> : <>
      <strong>{draft.source_name}</strong><small>Source revision / {draft.reference.source_request_id}</small>
      <pre>{draft.prompt}</pre>
      {stale && <p role="alert">Your draft changed during review. Discard this handoff and select the reference again.</p>}
    </>}
    <div className="handoff-actions"><button disabled={!connected || disabled || !draft || !!error || stale} onClick={() => {
      if (captured.current !== version.current || useStore.getState().currentProject !== project) return;
      onApply(draft);discard();
    }}>Apply brief to draft</button><button onClick={discard}>Discard handoff</button></div>
  </section>;
}

export function ReferenceNotice({reference, onClear, disabled}) {
  if (!reference) return null;
  return <section className="creative-reference" aria-label="Draft source reference"><Link2 size={16}/><div><strong>Recipe reference attached</strong><small>{reference.source_kind} / {reference.source_request_id}</small><p>This provenance is checked again before planning or building.</p></div><button disabled={disabled} onClick={onClear}>Detach reference</button></section>;
}
