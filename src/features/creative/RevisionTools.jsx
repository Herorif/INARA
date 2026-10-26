import React from 'react';
import { Undo2, Redo2, GitBranch, Copy, RotateCcw } from 'lucide-react';
import StatusChip from '../../shared/ui/StatusChip';
import { recipeDiff } from './draft.js';
import './revisions.css';
const show = value => value === undefined ? '(unset)' : JSON.stringify(value);
export function RecipeComparison({ before, after, title = 'Draft changes' }) {
  const changes = recipeDiff(before, after);
  return <details className="recipe-comparison"><summary>{title} <span className="recipe-comparison__count">{changes.length} fields</span></summary>
    {changes.length ? <div className="recipe-diff-scroll"><table><thead><tr><th scope="col" className="hud-label">Field</th><th scope="col" className="hud-label">Before</th><th scope="col" className="hud-label">After</th></tr></thead><tbody>{changes.map(change => <tr key={change.field}><th scope="row">{change.field}</th><td>{show(change.before)}</td><td>{show(change.after)}</td></tr>)}</tbody></table></div> : <p>No recipe changes.</p>}
  </details>;
}
export default function RevisionTools({ draft, base, jobs, selected, compare, onCompare, disabled, onNew }) {
  const dirty = !!base && recipeDiff(base.recipe, draft.recipe).length > 0;
  return <section className="revision-tools hud-panel" aria-label="Revision editing">
    <div className="revision-draft-heading"><span className="hud-label"><GitBranch size={14} aria-hidden="true" />{base ? `Branch from ${base.request_id.slice(0, 8)}` : 'Independent draft'}</span><StatusChip className={dirty ? 'draft-dirty' : ''} tone={dirty ? 'warn' : 'idle'}>{dirty ? 'Unsaved changes' : 'Recipe ready'}</StatusChip></div>
    <div className="revision-actions"><button type="button" className="btn btn--ghost btn--sm" aria-label="Undo recipe edit" disabled={disabled || !draft.canUndo} onClick={draft.undo}><Undo2 size={14} aria-hidden="true" />Undo</button><button type="button" className="btn btn--ghost btn--sm" aria-label="Redo recipe edit" disabled={disabled || !draft.canRedo} onClick={draft.redo}><Redo2 size={14} aria-hidden="true" />Redo</button>
      <button type="button" className="btn btn--ghost btn--sm" disabled={disabled || !base} onClick={() => draft.resetRecipe(base.recipe)}><RotateCcw size={14} aria-hidden="true" />Reload base</button>
      <button type="button" className="btn btn--ghost btn--sm" disabled={disabled} onClick={() => { onNew(); draft.setRecipe(value => ({ ...value, name: `${value.name.slice(0, 50)} copy` })); }}><Copy size={14} aria-hidden="true" />Independent copy</button></div>
    <p>{base ? 'Build creates a new child revision. Previous files stay intact.' : 'This draft starts a separate revision tree.'} Undo history stays in this panel.</p>
    {base && <RecipeComparison before={base.recipe} after={draft.recipe} />}
    <label className="revision-compare-label"><span>Compare saved revision</span><select aria-label="Compare saved revision" value={compare} onChange={event => onCompare(event.target.value)} disabled={disabled}><option value="">No comparison</option>{jobs.filter(job => job.state === 'succeeded' && job.request_id !== selected).map(job => <option key={job.request_id} value={job.request_id}>{job.recipe.name} / {job.request_id.slice(0, 8)}</option>)}</select></label>
  </section>;
}
