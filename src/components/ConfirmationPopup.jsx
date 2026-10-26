import React, { useCallback, useRef } from 'react';
import useStore from '../store';
import { emitSocket } from '../services/socket';
import { useDialogFocus } from '../app/useDialogFocus';
import HudLabel from '../shared/ui/HudLabel';

/** Shows the oldest pending approval; answering removes exactly that request id. */
export default function ConfirmationPopup() {
  const request = useStore(state => state.confirmationQueue[0] || null);
  const pending = useStore(state => state.confirmationQueue.length);
  const dialog = useRef(null);
  const respond = useCallback(confirmed => {
    if (!request) return;
    emitSocket('confirm_tool', { id: request.id, confirmed });
    useStore.getState().resolveConfirmation(request.id);
  }, [request]);
  const decline = useCallback(() => respond(false), [respond]);
  useDialogFocus(dialog, request ? decline : null);
  if (!request) return null;
  const action = request.tool?.replaceAll('_', ' ') || 'Assistant action';
  return <div ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="approval-title" aria-describedby="approval-summary" className="tool-confirmation-dialog approval-backdrop">
    <section className="approval-card" key={request.id}>
      <div className="approval-body">
        <div className="approval-top"><HudLabel className="approval-label">APPROVAL NEEDED</HudLabel>{pending > 1 && <HudLabel className="approval-count">{`1 of ${pending}`}</HudLabel>}</div>
        <h3 id="approval-title">{action}</h3>
        <p id="approval-summary">INARA continues only after you approve. Denying leaves this action undone.</p>
        {request.project && <p className="approval-project">Project · <strong>{request.project}</strong></p>}
        <details open><summary>Details</summary><pre>{JSON.stringify(request.args || {}, null, 2)}</pre></details>
      </div><footer><button type="button" className="btn btn--secondary" data-dialog-autofocus onClick={decline}>Deny</button><button type="button" className="btn btn--primary" onClick={() => respond(true)}>Approve</button></footer>
    </section></div>;
}
