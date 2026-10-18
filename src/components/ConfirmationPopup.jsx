import React, { useCallback, useRef } from 'react';
import useStore from '../store';
import { emitSocket } from '../services/socket';
import { useDialogFocus } from '../app/useDialogFocus';
import PanelHeader from '../app/PanelHeader';

export default function ConfirmationPopup() {
  const request = useStore(state => state.confirmationRequest);
  const dialog = useRef(null);
  const respond = useCallback(confirmed => {
    if (!request) return;
    emitSocket('confirm_tool', { id: request.id, confirmed });
    useStore.setState({ confirmationRequest: null });
  }, [request]);
  const decline = useCallback(() => respond(false), [respond]);
  useDialogFocus(dialog, request ? decline : null);
  if (!request) return null;
  return <div ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Approve assistant action" className="tool-confirmation-dialog approval-backdrop">
    <section className="approval-card"><PanelHeader title="Your permission, first" closeLabel="Decline action" onClose={decline} />
      <div className="approval-body"><span className="eyebrow">ACTION REQUEST</span><h3>{request.tool?.replaceAll('_', ' ')}</h3><p>Review this action before INARA continues. Declining leaves this request unapproved.</p>
        {request.project && <p className="approval-project">Project / <strong>{request.project}</strong></p>}
        <details open><summary>Review details</summary><pre>{JSON.stringify(request.args || {}, null, 2)}</pre></details>
      </div><footer><button className="voice-button" data-dialog-autofocus onClick={decline}>Deny Request</button><button className="primary-button" onClick={() => respond(true)}>Approve Action</button></footer>
    </section></div>;
}
