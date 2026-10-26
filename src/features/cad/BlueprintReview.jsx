import React, {useState} from 'react';
import DraftPreview from './DraftPreview';
import {RecipeComparison} from '../creative/RevisionTools';

export default function BlueprintReview({proposal, recipe, disabled, onApply, onDiscard}) {
  const [preview, setPreview] = useState(false);
  const parts = proposal.recipe.shape === 'scene' ? proposal.recipe.objects : null;
  return <section className="proposal-review hud-panel" aria-label="Blueprint proposal review">
    <span className="hud-label">Proposal / review before applying</span>
    <h4>{parts ? `Proposed scene: ${parts.length} parts` : 'Proposed changes'}</h4>
    <p>Applying replaces the current draft. Building is a separate action with its own approval. The blockout is an approximation, not validated geometry.</p>
    {parts && <div className="blueprint-parts">{parts.map((part, index) => <article key={index}><strong><span className="cad-id">{String(index + 1).padStart(2, '0')}</span> {part.name}</strong><span>{part.shape} / {part.material}</span><small>{[part.width, part.depth, part.height].join(' × ')} mm / position {part.position.join(', ')} mm</small></article>)}</div>}
    <button type="button" className="btn btn--secondary btn--sm" aria-pressed={preview} onClick={() => setPreview(value => !value)}>{preview ? 'Hide proposal preview' : 'Preview proposal'}</button>
    {preview && <DraftPreview recipe={proposal.recipe} selected={0} disabled readOnly onSelect={() => {}} onMove={() => {}}/>}
    <RecipeComparison before={recipe} after={proposal.recipe} title="Proposed field changes"/>
    <div className="blueprint-review-actions"><button type="button" className="btn btn--primary btn--sm" disabled={disabled} onClick={onApply}>Apply to draft</button><button type="button" className="btn btn--ghost btn--sm" onClick={onDiscard}>Discard proposal</button></div>
  </section>;
}
