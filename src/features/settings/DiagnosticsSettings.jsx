import React, { useEffect, useMemo, useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import socket, { emitSocket } from '../../services/socket';
import { createRpcScope } from '../../transport/rpc.ts';
import Switch from './Switch';
import { ResultMessage } from './SecretKeyRow';
import {
  EXPORT_HELP, EXPORT_LABEL, EXPORT_TIMEOUT, EXPORTING_LABEL, HEADING, TEXT_HELP, TEXT_LABEL,
  diagnosticsChoice, exportResult, includeTextPatch,
} from './diagnosticsModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const LINE = 'flex flex-wrap items-center justify-between gap-x-3 gap-y-2';

/**
 * Preferences > Diagnostics (S4.2). `diagnostics` is the saved settings.diagnostics; the
 * switch saves through update_settings and moves when the core echoes the settings.
 * The renderer has no safe open-folder action, so the saved path is shown as text.
 */
export default function DiagnosticsSettings({ diagnostics }) {
  const scope = useMemo(() => createRpcScope(socket), []);
  const choice = diagnosticsChoice(diagnostics);
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => () => scope.dispose(), [scope]);

  const run = async () => {
    setExporting(true);
    setResult(null);
    try { setResult(exportResult(await scope.call('diagnostics_export', {}, EXPORT_TIMEOUT))); }
    catch (error) { setResult(exportResult(error)); }
    finally { setExporting(false); }
  };
  const toggle = () => {
    const patch = includeTextPatch(choice, !choice.includeText);
    if (patch) emitSocket('update_settings', patch);
  };

  return <section className="flex flex-col gap-2" data-diagnostics-settings>
    <h3 className="hud-label">{HEADING}</h3>
    <div className={ROW}>
      <p className={HELP}>{EXPORT_HELP}</p>
      <div>
        <button type="button" className="btn btn--secondary btn--sm" disabled={exporting} onClick={run} aria-describedby="diagnostics-export-result">
          {exporting ? <Loader2 size={14} aria-hidden="true" className="animate-spin" /> : <Download size={14} aria-hidden="true" />}
          <span>{exporting ? EXPORTING_LABEL : EXPORT_LABEL}</span>
        </button>
      </div>
      <ResultMessage id="diagnostics-export-result" result={result} />
    </div>
    <div className={ROW}>
      <div className={LINE}>
        <span className="text-sm text-ink-1">{TEXT_LABEL}</span>
        <Switch checked={choice.includeText} label={TEXT_LABEL} onClick={toggle} />
      </div>
      <p className={HELP}>{TEXT_HELP}</p>
    </div>
  </section>;
}
