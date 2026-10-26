/*
 * Bundled UI fonts (SIL Open Font License 1.1), latin subset only; no runtime network requests.
 * Inter by Rasmus Andersson / The Inter Project Authors, via @fontsource-variable/inter.
 * JetBrains Mono by JetBrains, via @fontsource-variable/jetbrains-mono.
 *
 * The files are imported with `?url` (the same pattern as the MediaPipe WASM in
 * src/features/vision/tracker.js) so the renderer provenance plugin records them as inputs and
 * assets; plain CSS url() references are emitted by Vite without passing the provenance load hook.
 * Characters outside the latin range fall back to the next family in --font-sans / --font-mono.
 */
import interLatin from '@fontsource-variable/inter/files/inter-latin-wght-normal.woff2?url';
import monoLatin from '@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2?url';

const LATIN = 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD';

// FontFace API instead of an injected <style>, so the production CSP needs no style-src 'unsafe-inline'.
const FACES = [
  ['Inter Variable', '100 900', interLatin],
  ['JetBrains Mono Variable', '100 800', monoLatin],
];

if (typeof document !== 'undefined' && document.fonts && typeof FontFace !== 'undefined') {
  const loaded = new Set([...document.fonts].map(face => face.family.replace(/^["']|["']$/g, '')));
  for (const [family, weight, url] of FACES) {
    if (loaded.has(family)) continue;
    const face = new FontFace(family, `url("${url}") format('woff2')`, { style: 'normal', weight, display: 'swap', unicodeRange: LATIN });
    document.fonts.add(face);
    face.load().catch(() => { /* fall back to the next family in --font-sans / --font-mono */ });
  }
}
