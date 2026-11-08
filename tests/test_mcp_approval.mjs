import test from 'node:test';
import assert from 'node:assert/strict';
import { approvalView } from '../src/components/approvalView.js';

const SUMMARY = 'JARVIS continues only after you approve. Denying leaves this action undone.';

test('an MCP tool card names the server and the tool, with the arguments', () => {
  const card = approvalView({ id: 'a', tool: 'mcp__globe__fly_to', args: {
    arguments: { city: 'Kuala Lumpur', zoom: 9 }, server: 'God’s Eye', tool_title: 'Fly to', mcp_tool: 'fly_to',
  } });
  assert.deepEqual(card, {
    kind: 'mcp_tool', title: 'God’s Eye: Fly to', summary: SUMMARY, approveLabel: 'Approve', denyLabel: 'Deny',
    details: { city: 'Kuala Lumpur', zoom: 9 },
  });
});

test('the tool name stands in for a missing title', () => {
  const card = approvalView({ id: 'b', tool: 'mcp__globe__fly_to', args: { arguments: {}, server: 'Globe', mcp_tool: 'fly_to' } });
  assert.equal(card.title, 'Globe: fly_to');
  assert.deepEqual(card.details, {});
});

test('long arguments are clipped to a short JSON text', () => {
  const card = approvalView({ id: 'c', tool: 'mcp__notes__write', args: {
    arguments: { text: 'x'.repeat(2000) }, server: 'Notes', tool_title: 'Write',
  } });
  assert.equal(card.kind, 'mcp_tool');
  assert.equal(typeof card.details.arguments, 'string');
  assert.ok(card.details.arguments.length <= 601 && card.details.arguments.endsWith('…'));
  assert.ok(card.details.arguments.startsWith('{"text":"xxx'));
});

test('the title is clipped and a card without a server is generic', () => {
  const card = approvalView({ id: 'd', tool: 'mcp__a__b', args: { server: 'S'.repeat(100), tool_title: 'T'.repeat(100), arguments: {} } });
  assert.equal(card.title.length, 160);
  assert.equal(approvalView({ id: 'e', tool: 'mcp__a__b', args: { arguments: {} } }).kind, 'generic');
  assert.equal(approvalView({ id: 'f', tool: 'other_tool', args: { server: 'S' } }).kind, 'generic');
});
