import React, { useCallback, useRef } from 'react';
import useStore from '../store';
import { emitSocket } from '../services/socket';
import { useDialogFocus } from '../app/useDialogFocus';
import HudLabel from '../shared/ui/HudLabel';
import { approvalView } from './approvalView';

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
  const view = approvalView(request);
  return <div ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="approval-title" aria-describedby="approval-summary" className="tool-confirmation-dialog approval-backdrop">
    <section className="approval-card" key={request.id}>
      <div className="approval-body">
        <div className="approval-top"><HudLabel className="approval-label">APPROVAL NEEDED</HudLabel>{pending > 1 && <HudLabel className="approval-count">{`1 of ${pending}`}</HudLabel>}</div>
        <h3 id="approval-title">{view.title}</h3>
        <p id="approval-summary">{view.summary}</p>
        {request.project && <p className="approval-project">Project · <strong>{request.project}</strong></p>}
        {view.details && <details open><summary>Details</summary><pre>{JSON.stringify(view.details, null, 2)}</pre></details>}
      </div><footer><button type="button" className="btn btn--secondary" data-dialog-autofocus onClick={decline}>{view.denyLabel}</button><button type="button" className="btn btn--primary" onClick={() => respond(true)}>{view.approveLabel}</button></footer>
    </section></div>;
}
