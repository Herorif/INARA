import React from 'react';
import { Undo2, Redo2, GitBranch, Copy, RotateCcw } from 'lucide-react';
import { recipeDiff } from './draft.js';
import './revisions.css';
const show = value => value === undefined ? '(unset)' : JSON.stringify(value);
export function RecipeComparison({ before, after, title = 'Draft changes' }) {
  const changes = recipeDiff(before, after);
  return <details className="recipe-comparison"><summary>{title} <span>{changes.length} fields</span></summary>
    {changes.length ? <div className="recipe-diff-scroll"><table><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>{changes.map(change => <tr key={change.field}><th scope="row">{change.field}</th><td>{show(change.before)}</td><td>{show(change.after)}</td></tr>)}</tbody></table></div> : <p>No recipe changes.</p>}
  </details>;
}
export default function RevisionTools({ draft, base, jobs, selected, compare, onCompare, disabled, onNew }) {
  const dirty = !!base && recipeDiff(base.recipe, draft.recipe).length > 0;
  return <section className="revision-tools" aria-label="Revision editing">
    <div className="revision-draft-heading"><span className="eyebrow"><GitBranch size={14} />{base ? `BRANCH FROM ${base.request_id.slice(0, 8)}` : 'INDEPENDENT DRAFT'}</span><span className={dirty ? 'draft-dirty' : ''}>{dirty ? 'Unsaved changes' : 'Recipe ready'}</span></div>
    <div className="revision-actions"><button type="button" aria-label="Undo recipe edit" disabled={disabled || !draft.canUndo} onClick={draft.undo}><Undo2 size={14} />Undo</button><button type="button" aria-label="Redo recipe edit" disabled={disabled || !draft.canRedo} onClick={draft.redo}><Redo2 size={14} />Redo</button>
      <button type="button" disabled={disabled || !base} onClick={() => draft.resetRecipe(base.recipe)}><RotateCcw size={14} />Reload base</button>
      <button type="button" disabled={disabled} onClick={() => { onNew(); draft.setRecipe(value => ({ ...value, name: `${value.name.slice(0, 50)} copy` })); }}><Copy size={14} />Independent copy</button></div>
    <p>{base ? 'Build creates a new child revision. Previous files stay intact.' : 'This draft will start a separate revision tree.'} Undo history stays in this panel.</p>
    {base && <RecipeComparison before={base.recipe} after={draft.recipe} />}
    <label className="revision-compare-label">Compare saved revision<select aria-label="Compare saved revision" value={compare} onChange={event => onCompare(event.target.value)} disabled={disabled}><option value="">No comparison</option>{jobs.filter(job => job.state === 'succeeded' && job.request_id !== selected).map(job => <option key={job.request_id} value={job.request_id}>{job.recipe.name} / {job.request_id.slice(0, 8)}</option>)}</select></label>
  </section>;
}
