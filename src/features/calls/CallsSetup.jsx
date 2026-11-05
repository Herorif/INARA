import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Copy } from 'lucide-react';
import socket from '../../services/socket';
import StatusChip from '../../shared/ui/StatusChip';
import HudLabel from '../../shared/ui/HudLabel';
import SecretKeyRow from '../settings/SecretKeyRow';
import { PROVIDERS, rpcFailureMessage } from '../settings/aiSettingsModel';
import { createSecretsClient } from '../../transport/secretsClient.ts';
import { CANCEL_FORWARDING, FORWARDING_STORAGE_KEY, forwardingCodes, setupRows } from './callsModel';
import { readMigrated } from '../../services/storageKeys';

const number = { inputType: 'tel', inputMode: 'tel', noun: 'number', checkable: false, removedText: 'Number removed.', removeConfirm: 'Remove this number? JARVIS will stop using it.', emptyText: 'Enter the number first.' };
export const CALL_KEYS = {
  twilio_account_sid: { name: 'twilio_account_sid', title: 'Account SID', provider: 'Twilio', inputLabel: 'Twilio Account SID', noun: 'SID', purpose: 'Starts with AC.', removedText: 'SID removed.', emptyText: 'Paste the Account SID first.' },
  twilio_auth_token: { name: 'twilio_auth_token', title: 'Auth Token', provider: 'Twilio', inputLabel: 'Twilio Auth Token', noun: 'token', purpose: 'Twilio signs every request to JARVIS with it.', removedText: 'Token removed.', emptyText: 'Paste the Auth Token first.' },
  twilio_phone_number: { name: 'twilio_phone_number', title: 'JARVIS number', provider: 'Twilio', inputLabel: 'JARVIS number, for example +60312345678', purpose: 'Your Malaysian Twilio number in +60 format.', ...number },
  owner_phone_number: { name: 'owner_phone_number', title: 'Your mobile', provider: 'Twilio', inputLabel: 'Your mobile number, for example +60123456789', purpose: 'JARVIS phones you here with briefings.', ...number },
  cloudflare_tunnel_token: { name: 'cloudflare_tunnel_token', title: 'Tunnel token', provider: 'Cloudflare', inputLabel: 'Cloudflare tunnel token', noun: 'token', checkable: false, purpose: "Only the token from the tunnel's install command.", removedText: 'Token removed.', emptyText: 'Paste the tunnel token first.' },
};
const GEMINI = PROVIDERS.find(entry => entry.name === 'gemini_api_key');
const COMPANION = { twilio_account_sid: 'twilio_auth_token', twilio_auth_token: 'twilio_account_sid' };
const STEPS = [
  'Buy a Malaysian local number in Twilio. Its regulatory bundle can take several days.',
  'Create a Cloudflare tunnel with a published route to http://localhost:8790 and copy its token.',
  'Install cloudflared on this PC.',
  'Enter each value below, then the public address in Call settings.',
  "Point the Twilio number's incoming-call webhook at your public address followed by /telephony/voice/inbound, and its status callback at /telephony/status.",
  'Dial the forwarding codes on your phone.',
  'Turn answering on and make a test call.',
];

const readForwarding = () => { try { return readMigrated(localStorage, FORWARDING_STORAGE_KEY) === '1'; } catch { return false; } };
const writeForwarding = value => { try { localStorage.setItem(FORWARDING_STORAGE_KEY, value ? '1' : '0'); } catch { /* per-viewer convenience only */ } };

function CopyCode({ code, label }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { setCopied(false); }
  };
  return <div className="calls-code">
    <span className="calls-code__label">{label}</span>
    <code className="calls-code__value">{code}</code>
    <button type="button" className="btn btn--ghost btn--sm" aria-label={`Copy ${label.toLowerCase()} code`} onClick={copy}>
      <Copy size={14} aria-hidden="true" />{copied ? 'Copied' : 'Copy'}
    </button>
  </div>;
}

// Defined at module level so key rows keep their edit state across re-renders.
function Row({ row, help, children }) {
  return <section className="calls-setup__row hud-panel" aria-labelledby={`calls-setup-${row.id}`} data-setup={row.id}>
    <div className="calls-setup__head">
      <h3 id={`calls-setup-${row.id}`}>{row.title}{!row.required && <span className="calls-setup__optional"> (recommended)</span>}</h3>
      <StatusChip tone={row.tone}>{row.label}</StatusChip>
    </div>
    {help && <p className="calls-setup__help">{help}</p>}
    {children}
  </section>;
}

/** Setup checklist: one row per part the core reports on, with its key rows inline. */
export default function CallsSetup({ status, onStatusChange, onOpenSettings, onBack }) {
  const client = useMemo(() => createSecretsClient(socket), []);
  const [secrets, setSecrets] = useState({});
  const [loadError, setLoadError] = useState('');
  const [forwarding, setForwarding] = useState(readForwarding);

  useEffect(() => () => client.dispose(), [client]);
  const load = useCallback(() => {
    client.status().then(list => { setSecrets(Object.fromEntries(list.map(item => [item.name, item]))); setLoadError(''); })
      .catch(error => setLoadError(rpcFailureMessage(error)));
  }, [client]);
  useEffect(() => { load(); return client.on('connect', load); }, [client, load]);

  const onStatus = useCallback(next => {
    setSecrets(current => ({ ...current, [next.name]: next }));
    onStatusChange?.();
  }, [onStatusChange]);
  // A Twilio value is checked together with its companion; re-check the other once this one passes.
  const onSaved = useCallback(saved => {
    const other = COMPANION[saved.name];
    if (!other || !saved.last_check?.ok || !secrets[other]?.configured) return;
    client.test(other).then(onStatus).catch(() => {});
  }, [client, secrets, onStatus]);

  const rows = Object.fromEntries(setupRows(status, forwarding).map(row => [row.id, row]));
  const key = name => <SecretKeyRow key={name} idPrefix="calls-key" entry={CALL_KEYS[name] || GEMINI} status={secrets[name]} client={client} onStatus={onStatus} onSaved={onSaved} />;
  const tunnelHelp = rows.tunnel.label === 'CLOUDFLARED MISSING'
    ? <>Install cloudflared, then restart answering: <code className="calls-inline-code">winget install --id Cloudflare.cloudflared</code></>
    : rows.tunnel.label === 'FAILED' ? 'The tunnel stopped. Check the token and your internet connection.'
      : 'A secure link from the internet to JARVIS’s phone gateway only. JARVIS starts it while answering is on.';

  return <div className="calls-setup" aria-labelledby="calls-setup-title">
    <div className="calls-setup__top">
      <HudLabel as="h2" id="calls-setup-title">SET UP CALLS</HudLabel>
      {onBack && <button type="button" className="btn btn--ghost btn--sm" onClick={onBack}>Back to calls</button>}
    </div>
    {loadError && <p className="calls-error" role="alert">{loadError}</p>}
    <Row row={rows.twilio} help="Twilio Console home → Account info. JARVIS checks both values with Twilio.">{key('twilio_account_sid')}{key('twilio_auth_token')}</Row>
    <Row row={rows.jarvis_number}>{key('twilio_phone_number')}</Row>
    <Row row={rows.owner_number}>{key('owner_phone_number')}</Row>
    <Row row={rows.tunnel} help={tunnelHelp}>{key('cloudflare_tunnel_token')}</Row>
    <Row row={rows.address} help="The https address of your tunnel’s published route, for example https://calls.example.com.">
      <div className="calls-setup__line">
        <span className={status?.public_base_url ? 'calls-mono' : 'calls-muted'}>{status?.public_base_url || 'Not set'}</span>
        <button type="button" className="btn btn--secondary btn--sm" onClick={() => onOpenSettings('public-address')}>{status?.public_url_configured ? 'Change address' : 'Set address'}</button>
      </div>
    </Row>
    <Row row={rows.voice} help="The phone voice uses your Gemini key.">{key('gemini_api_key')}</Row>
    <Row row={rows.forwarding} help="Dial these on your phone so your carrier passes missed calls to JARVIS.">
      <div className="calls-codes">
        {forwardingCodes(status?.jarvis_number).map(entry => <CopyCode key={entry.id} label={entry.label} code={entry.code} />)}
        <CopyCode label="Cancel all forwarding" code={CANCEL_FORWARDING} />
      </div>
      {!status?.jarvis_number && <p className="calls-setup__help">Replace &lt;JARVIS number&gt; with your Twilio number, in +60 or 0 form, whichever your carrier accepts.</p>}
      <label className="calls-check">
        <input type="checkbox" checked={forwarding} onChange={event => { setForwarding(event.target.checked); writeForwarding(event.target.checked); }} />
        <span>I’ve set up call forwarding</span>
      </label>
    </Row>
    <section className="calls-setup__guide hud-panel" aria-labelledby="calls-setup-guide">
      <HudLabel as="h3" id="calls-setup-guide">SETUP STEPS</HudLabel>
      <ol>{STEPS.map(step => <li key={step}>{step}</li>)}</ol>
      <p className="calls-setup__help">See CALLS_SETUP.md in the JARVIS folder for the full guide.</p>
    </section>
  </div>;
}
