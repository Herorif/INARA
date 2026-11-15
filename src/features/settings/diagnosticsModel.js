// Pure copy and mappings for Preferences > Diagnostics (S4.2): the export result and the
// diagnostics.include_text switch (backend/services/diagnostics.py, docs/DIAGNOSTICS.md).

export const HEADING = 'Diagnostics';
export const EXPORT_LABEL = 'Export diagnostics';
export const EXPORTING_LABEL = 'Exporting…';
export const EXPORT_HELP = 'Saves recent logs, versions and settings, with keys and personal details removed, to a zip you can share when you need help.';
export const TEXT_LABEL = 'Include message text in traces';
export const TEXT_HELP = 'Off by default. Turn on only while you need help with a problem.';
export const EXPORT_FAILED = 'Diagnostics couldn’t be saved. Try again.';
// The core reads logs and lists audio devices (bounded at 5 s) before writing the zip.
export const EXPORT_TIMEOUT = 30000;

/** Saved `settings.diagnostics` -> { includeText }; anything but true reads as off. */
export function diagnosticsChoice(diagnostics) {
  const value = diagnostics && typeof diagnostics === 'object' ? diagnostics : {};
  return { includeText: value.include_text === true };
}

/** The update_settings patch for the switch, or null when nothing changes. */
export function includeTextPatch(choice, includeText) {
  if (typeof includeText !== 'boolean' || includeText === choice.includeText) return null;
  return { diagnostics: { include_text: includeText } };
}

/** diagnostics_export's answer (or a thrown RpcError) -> { tone, text, path? }. */
export function exportResult(result) {
  if (result && typeof result === 'object' && result.ok === true && typeof result.path === 'string' && result.path) {
    return { tone: 'ok', text: `Saved to ${result.path}`, path: result.path };
  }
  const message = result && typeof result === 'object' && typeof result.message === 'string' ? result.message : '';
  return { tone: 'danger', text: message || EXPORT_FAILED };
}
