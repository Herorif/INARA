/** Guard proposal data before it reaches the interactive draft preview. */
export function isCadRecipe(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const recipe = value as Record<string, any>;
  const number = (n: unknown, low: number, high: number) => typeof n === 'number' && Number.isFinite(n) && n >= low && n <= high;
  const name = (n: unknown) => typeof n === 'string' && n.trim().length > 0 && n.length <= 60 && !/[\x00-\x1f]/.test(n);
  const solid = (part: Record<string, any>) => !!part && name(part.name) && ['box', 'bracket', 'enclosure'].includes(part.shape) &&
    ['width', 'depth', 'height'].every(key => number(part[key], 1, 1000)) && number(part.thickness, .5, 100) &&
    (part.shape === 'box' || Math.min(part.depth, part.height) - part.thickness >= .5) &&
    (part.shape !== 'enclosure' || Math.min(part.width, part.depth) - 2 * part.thickness >= .5);
  const vector = (v: unknown, low: number, high: number) => Array.isArray(v) && v.length === 3 && v.every(n => number(n, low, high));
  if (!name(recipe.name) || recipe.engine != null && !['offline', 'blender'].includes(recipe.engine)) return false;
  if (recipe.shape !== 'scene') return recipe.objects == null && solid(recipe);
  return Array.isArray(recipe.objects) && recipe.objects.length >= 1 && recipe.objects.length <= 8 && recipe.objects.every(part =>
    solid(part) && vector(part.position, -2000, 2000) && vector(part.rotation, -360, 360) && vector(part.scale, .1, 5) &&
    ['cyan', 'titanium', 'amber', 'ceramic'].includes(part.material));
}
