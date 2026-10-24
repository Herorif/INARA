import React, {useState} from 'react';
import DraftPreview from './DraftPreview';
import {RecipeComparison} from '../creative/RevisionTools';

export default function BlueprintReview({proposal, recipe, disabled, onApply, onDiscard}) {
  const [preview, setPreview] = useState(false);
  const parts = proposal.recipe.shape === 'scene' ? proposal.recipe.objects : null;
  return <section className="proposal-review" aria-label="Blueprint proposal review">
    <span className="eyebrow">PROPOSAL / REVIEW BEFORE APPLYING</span>
    <h4>{parts ? `${parts.length} parts. One new possibility.` : 'Review your proposed changes'}</h4>
    <p>Applying replaces the current draft. Building remains a separate action with its own approval. This blockout is an approximation, not validated geometry.</p>
    {parts && <div className="blueprint-parts">{parts.map((part, index) => <article key={index}><strong>{String(index + 1).padStart(2, '0')} / {part.name}</strong><span>{part.shape} · {part.material}</span><small>{[part.width, part.depth, part.height].join(' × ')} mm · position {part.position.join(', ')} mm</small></article>)}</div>}
    <button type="button" aria-pressed={preview} onClick={() => setPreview(value => !value)}>{preview ? 'Hide proposal preview' : 'Preview proposal'}</button>
    {preview && <DraftPreview recipe={proposal.recipe} selected={0} disabled readOnly onSelect={() => {}} onMove={() => {}}/>}
    <RecipeComparison before={recipe} after={proposal.recipe} title="Proposed field changes"/>
    <div className="blueprint-review-actions"><button disabled={disabled} onClick={onApply}>Apply to draft</button><button onClick={onDiscard}>Discard proposal</button></div>
  </section>;
}
