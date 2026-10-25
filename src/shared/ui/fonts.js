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

const face = (family, weight, url) => `@font-face{font-family:'${family}';font-style:normal;font-display:swap;font-weight:${weight};src:url("${url}") format('woff2-variations');unicode-range:${LATIN};}`;

if (typeof document !== 'undefined' && !document.querySelector('style[data-inara-fonts]')) {
  const style = document.createElement('style');
  style.dataset.inaraFonts = '';
  style.textContent = face('Inter Variable', '100 900', interLatin) + face('JetBrains Mono Variable', '100 800', monoLatin);
  document.head.prepend(style);
}
