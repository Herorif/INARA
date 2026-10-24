import React, {useEffect, useRef, useState} from 'react';
import {ShieldCheck, Square, PhoneCall, RefreshCw} from 'lucide-react';
import socket from '../services/socket';
import {createCallTestingClient} from '../transport/callTestingClient.ts';

const labels = {policy_disabled: 'Controlled-test policy is disabled', channel_disabled: 'This call channel is not permitted',
  profile_missing: 'Prepare an observed enrollment draft', profile_changed: 'Enrollment or software changed; prepare again',
  evidence_missing: 'Physical capture and verification are still pending', evidence_invalid: 'Physical evidence expired or no longer matches',
  components_missing: 'Local speech or bridge components need setup', resource_policy: 'Leave gaming or resident mode',
  resources_busy: 'Another worker owns the resources', resource_capacity: 'Available capacity is insufficient', resource_fault: 'Resource checks need attention'};
const confirmationText = 'ANSWER ONE CONTROLLED TEST CALL';

export default function ControlledCallTest({project, connected}) {
  const [report, setReport] = useState(null), [review, setReview] = useState(null), [profile, setProfile] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [confirmation, setConfirmation] = useState('');
  const [now, setNow] = useState(Date.now());
  const api = useRef(null), epoch = useRef(0), active = useRef(null), mutating = useRef(false), refresh = useRef(() => {});
  const version = useRef(0);
  useEffect(() => {
    const generation = ++epoch.current, client = createCallTestingClient(socket, project);
    api.current = client; active.current = null; mutating.current = false;
    version.current++;
    setReport(null); setReview(null); setProfile(''); setError(''); setBusy(false); setConfirmation('');
    let reading = false;
    refresh.current = async () => {
      if (reading || mutating.current || !socket.connected) return;
      reading = true;
      const requestVersion = ++version.current;
      try {
        const value = await client.state();
        if (generation === epoch.current && requestVersion === version.current && !mutating.current) {
          setReport(value); active.current = value.active_id;
          setReview(previous => previous && value.ready && previous.revision === value.draft?.revision ? previous : null);
        }
      } catch (failure) { if (generation === epoch.current && requestVersion === version.current) { setError(failure.message); setReport(null); setReview(null); } }
      finally { reading = false; }
    };
    refresh.current();
    const timer = setInterval(() => {setNow(Date.now()); if (!document.hidden) refresh.current();}, 2000);
    return () => {
      epoch.current++; clearInterval(timer);
      // The request UUID is retained before Arm, including a lost acknowledgement.
      if (active.current && socket.connected) client.stop(active.current).catch(() => {});
      active.current = null; client.dispose();
    };
  }, [project, connected]);
  const act = async operation => {
    const generation = epoch.current;
    const requestVersion = ++version.current;
    mutating.current = true; setBusy(true); setError('');
    try {
      const value = await operation();
      if (generation !== epoch.current || requestVersion !== version.current) return;
      if ('worker_busy' in value) {setReport(value); active.current = value.active_id;}
      else setReview(value);
    } catch (failure) {if (generation === epoch.current && requestVersion === version.current) {setError(failure.message); setReview(null);}}
    finally {if (generation === epoch.current && requestVersion === version.current) {mutating.current = false; setBusy(false);}}
  };
  const leaseId = report?.active_id || active.current;
  const fresh = review?.ready && review.expires_at * 1000 > now && report?.ready && report?.draft?.revision === review.revision;
  return <section className="call-lab__enrollment" aria-label="Controlled one-call test">
    <div className="call-lab__test-heading"><ShieldCheck size={23}/><div><span className="eyebrow">CONTROLLED TEST / ONE CALL</span><h3>Prepare. Verify. Arm deliberately.</h3></div>
      <button aria-label="Refresh controlled-test readiness" disabled={!connected || busy} onClick={() => refresh.current()}><RefreshCw size={15}/></button></div>
    <p>Save an observed enrollment draft. Profile flags cannot prove audio isolation or call controls. A backend physical capture must pass before any one-call lease is offered.</p>
    <label htmlFor="call-test-profile">Observed bridge profile JSON</label>
    <textarea id="call-test-profile" value={profile} onChange={event => setProfile(event.target.value.slice(0, 16384))} spellCheck={false}
      disabled={busy || !!report?.worker_busy} placeholder="Paste an observed profile here. route_confirmed and controls_confirmed must both be false." rows={5}/>
    <button disabled={!connected || busy || !profile.trim() || report?.worker_busy} onClick={() => act(async () => {
      const parsed = JSON.parse(profile); setReview(null); setConfirmation(''); setProfile('');
      return api.current.prepare({profile: parsed});
    })}>Validate and save draft</button>
    {report?.draft && <p className="call-lab__draft">{report.draft.channel === 'sim' ? 'SIM' : 'Personal WhatsApp'} / max {report.draft.max_seconds}s<br/><small>Profile fingerprint: {report.draft.profile_sha256}</small></p>}
    {!!report?.blockers.length && <ul className="call-lab__blockers" aria-label="Controlled-test blockers">{report.blockers.map(code => <li key={code}>{labels[code]}</li>)}</ul>}
    {error && <p role="alert" className="call-lab__test-error">{error} An uncertain arm request is never retried automatically.</p>}
    <div className="call-lab__actions"><button disabled={!connected || busy || !report?.draft || report?.worker_busy} onClick={() => act(() => api.current.review(report.draft.revision))}>Review one-call readiness</button>
      {leaseId && <button disabled={!connected} onClick={() => {setReview(null); return act(() => api.current.stop(leaseId));}}><Square size={15}/>Stop and disarm</button>}</div>
    {leaseId && <p role="status">One-call lease requested or in progress. Check the call client if cleanup becomes uncertain.</p>}
    {review && !review.ready && <p role="status">Arming remains locked. Complete the listed physical and policy checks first.</p>}
    {review?.ready && <div className="call-lab__arm-review"><p>One use / expires {new Date(review.expires_at * 1000).toLocaleTimeString()}. Waits up to 30 seconds for one incoming call. Local structured speech only.</p>
      <label htmlFor="call-test-confirm">Type {confirmationText}</label><input id="call-test-confirm" value={confirmation} onChange={event => setConfirmation(event.target.value)} autoComplete="off" disabled={busy}/>
      <button disabled={!connected || busy || !fresh || confirmation !== confirmationText} onClick={() => {
        const current = review, id = crypto.randomUUID(); active.current = id; setReview(null); setConfirmation('');
        return act(() => api.current.arm({revision: current.revision, review_id: current.review_id, request_id: id, confirmation: confirmationText}));
      }}><PhoneCall size={15}/>Arm one controlled call</button></div>}
    <p>Closing this panel, disconnecting, locking, changing project or entering gaming mode stops its owned lease. No unattended answering or model benchmark is enabled.</p>
  </section>;
}
