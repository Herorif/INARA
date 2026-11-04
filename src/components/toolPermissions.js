// Tool permission policy <-> settings value mapping. Mirrors backend/services/tools.py
// permission_policy(): "deny" never runs, true asks first, false / "allow_within_scope"
// run without asking. Missing keys ask, except default-deny keys.

export const DEFAULT_DENY_PERMISSIONS = new Set(['legacy_generated_cad']);
// Always ask, whatever is stored (backend ToolSpec.always_ask); only "deny" changes them.
export const ALWAYS_ASK_PERMISSIONS = new Set(['place_task_call']);

export const PERMISSION_OPTIONS = [
  { id: 'never', label: 'Never', value: 'deny' },
  { id: 'ask', label: 'Ask first', value: true },
  { id: 'allow', label: 'Allow', value: false },
];

/** Option id ('never' | 'ask' | 'allow') for the stored policy of one tool. */
export function permissionOption(permissions, key) {
  const present = permissions != null && typeof permissions === 'object' && Object.hasOwn(permissions, key);
  if (!present) return DEFAULT_DENY_PERMISSIONS.has(key) ? 'never' : 'ask';
  const stored = permissions[key];
  if (stored === 'deny') return 'never';
  if (ALWAYS_ASK_PERMISSIONS.has(key)) return 'ask';
  if (stored === false || stored === 'allow_within_scope') return 'allow';
  // The backend asks for any other stored value, including true.
  return 'ask';
}

/** Settings value to send for an option id. */
export function permissionValue(option) {
  const match = PERMISSION_OPTIONS.find(entry => entry.id === option);
  if (!match) throw new Error(`Unknown permission option: ${option}`);
  return match.value;
}
