import { createRpcScope, RpcError } from '../../transport/rpc.ts';

/**
 * Owner-only People RPCs (P1, telephony/contacts.py). Every acknowledgement is checked here.
 * The people list is the owner's own, so numbers arrive in full (E.164).
 */

const GROUPS = ['vip', 'known', 'blocked'];
const ID = /^[0-9a-f-]{36}$/;
const E164 = /^\+[1-9][0-9]{6,14}$/;

const isObject = value => !!value && typeof value === 'object' && !Array.isArray(value);
const isText = (value, limit) => typeof value === 'string' && value.length <= limit;

export const isPerson = (value, draft = false) => isObject(value)
  && (draft ? value.id === null || ID.test(value.id) : typeof value.id === 'string' && ID.test(value.id))
  && isText(value.name, 60) && (draft || value.name.length > 0)
  && Array.isArray(value.numbers) && value.numbers.length >= 1 && value.numbers.length <= 5
  && value.numbers.every(number => typeof number === 'string' && E164.test(number))
  && GROUPS.includes(value.group) && isText(value.note ?? '', 300);

const invalid = () => new RpcError('The core returned an incomplete person. Try again.', 'invalid_response');

export function createPeopleClient(socket) {
  const scope = createRpcScope(socket);
  const person = response => { if (!isPerson(response.person)) throw invalid(); return response.person; };
  return {
    on: scope.on,
    dispose: scope.dispose,
    async list() {
      const response = await scope.call('contacts_list', {});
      if (!Array.isArray(response.people) || !response.people.every(item => isPerson(item))) throw invalid();
      return response.people;
    },
    /** Create (id null) or update; fails with the core's code (invalid_name, invalid_number, duplicate_number, …). */
    async save({ id, name, numbers, group, note }) {
      return person(await scope.call('contacts_save', { ...(id ? { id } : {}), name, numbers, group, note }));
    },
    async remove(id) { await scope.call('contacts_delete', { id }); },
    /** "Add to people" from a call: { existing, person } (an unsaved draft has id null). */
    async callDraft(callId) {
      const response = await scope.call('contacts_call_draft', { id: callId });
      if (typeof response.existing !== 'boolean' || !isPerson(response.person, !response.existing)) throw invalid();
      return { existing: response.existing, person: response.person };
    },
    /** "Mark VIP" / "Block" from a call. */
    async callMark(callId, group) {
      if (!GROUPS.includes(group)) throw new RpcError('Unknown group.', 'invalid_arguments');
      return person(await scope.call('contacts_call_mark', { id: callId, group }));
    },
  };
}
