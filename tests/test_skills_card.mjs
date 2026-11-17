// S5.2 skills (docs/SKILLS.md): the "Teach JARVIS" approval card shows the exact SKILL.md.
import test from 'node:test';
import assert from 'node:assert/strict';
import { approvalView } from '../src/components/approvalView.js';

const SKILL_MD = '---\nname: "Gym bag"\ndescription: "Pack the gym bag."\n---\n\n1. Towel.\n';

test('teach_skill shows the SKILL.md text with Save skill / Not now', () => {
  const view = approvalView({ id: 'a', tool: 'teach_skill', args: { name: 'Gym bag', slug: 'gym-bag', skill_md: SKILL_MD, replaces: null } });
  assert.deepEqual(view, {
    kind: 'teach_skill', title: 'Teach JARVIS a skill?',
    summary: 'JARVIS will save this as a skill it can follow later.',
    approveLabel: 'Save skill', denyLabel: 'Not now', details: SKILL_MD,
  });
});

test('replacing an owner skill says so in the summary', () => {
  const view = approvalView({ id: 'b', tool: 'teach_skill', args: { skill_md: SKILL_MD, replaces: 'Replaces your existing skill gym-bag.' } });
  assert.equal(view.summary, 'JARVIS will save this as a skill it can follow later. Replaces your existing skill gym-bag.');
  assert.equal(view.details, SKILL_MD);
});

test('without the file the card falls back to the generic layout', () => {
  for (const args of [{}, { skill_md: '' }, { skill_md: 42 }]) {
    const view = approvalView({ id: 'c', tool: 'teach_skill', args });
    assert.equal(view.kind, 'generic');
    assert.equal(view.approveLabel, 'Approve');
  }
});
