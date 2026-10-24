import { useEffect } from 'react';
export function useDialogFocus(ref, onClose) {
  useEffect(() => {
    if (!onClose) return;
    const previous = document.activeElement;
    (ref.current?.querySelector('[data-dialog-autofocus]') || ref.current)?.focus();
    const onKey = event => {
      const dialogs = [...document.querySelectorAll('[role="dialog"][aria-modal="true"]')].filter(value => value.getClientRects().length);
      if (dialogs.at(-1) !== ref.current) return;
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key !== 'Tab' || !ref.current) return;
      const items = [...ref.current.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]')].filter(el => el.getClientRects().length);
      const first = items[0], last = items.at(-1);
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === ref.current)) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); if (previous?.isConnected) previous.focus(); };
  }, [ref, onClose]);
}
