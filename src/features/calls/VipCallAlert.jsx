import React from 'react';
import useStore from '../../store';
import HudLabel from '../../shared/ui/HudLabel';
import { alertCopy, callBackFocus } from './callAlertModel';
import './callAlert.css';

/**
 * P1: a VIP called while the workspace is open. "Call back" opens Calls on that record with
 * its callback approval focused; it never places a call itself. "Dismiss" hides the card only.
 */
export default function VipCallAlert({ stacked = false }) {
  const alert = useStore(state => state.callAlerts.alert);
  const locked = useStore(state => state.isLockScreenVisible);
  if (!alert || locked) return null;
  const copy = alertCopy(alert);
  const store = useStore.getState;
  const callBack = () => { store().focusCall(callBackFocus(alert)); store().dismissVipAlert(); };
  return <section className={`vip-call-alert hud-panel hud-frame ${stacked ? 'vip-call-alert--stacked' : ''}`} role="alertdialog" aria-live="assertive"
    aria-labelledby="vip-call-alert-title" aria-describedby="vip-call-alert-summary" data-record={alert.recordId}>
    <HudLabel className="vip-call-alert__label">{copy.label}</HudLabel>
    <h2 id="vip-call-alert-title" className="vip-call-alert__title">{copy.title}</h2>
    <p id="vip-call-alert-summary" className="vip-call-alert__summary">{copy.summary}</p>
    <div className="vip-call-alert__actions">
      <button type="button" className="btn btn--primary btn--sm" onClick={callBack}>Call back</button>
      <button type="button" className="btn btn--secondary btn--sm" onClick={() => store().dismissVipAlert()}>Dismiss</button>
    </div>
  </section>;
}
