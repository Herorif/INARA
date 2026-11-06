/**
 * The crystal J brand mark (src/assets/icons/mark-<px>.png, published by
 * scripts/build-icons.py): which file is the 1x and which the 2x image at each CSS size.
 * 24 is the pixel-grid frame, 32 the simplified render, 48 and up the full renders.
 */
export const BRAND_MARK_SIZES = Object.freeze({
  24: Object.freeze([24, 48]),
  32: Object.freeze([32, 64]),
  48: Object.freeze([48, 96]),
});

/** `<img>` props for the mark at `size` CSS px; `urls` maps a file's px size to its URL. */
export function brandMarkProps(size, urls) {
  const pair = Number.isInteger(size) ? BRAND_MARK_SIZES[size] : undefined;
  if (!pair) throw new RangeError(`No brand mark at ${size} px`);
  const [one, two] = pair.map(px => {
    if (!urls[px]) throw new RangeError(`Missing mark-${px}.png`);
    return urls[px];
  });
  return {
    src: one,
    srcSet: `${one} 1x, ${two} 2x`,
    width: size,
    height: size,
    alt: '',
    'aria-hidden': 'true',
    draggable: 'false',
  };
}
