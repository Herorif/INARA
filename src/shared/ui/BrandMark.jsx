import React from 'react';
// ?no-inline: emitted files, never data: URLs. Chromium picks any data: candidate in a srcset
// as already available, so an inlined 2x would replace the pixel-grid 1x even at 100%.
import mark24 from '../../assets/icons/mark-24.png?no-inline';
import mark32 from '../../assets/icons/mark-32.png?no-inline';
import mark48 from '../../assets/icons/mark-48.png?no-inline';
import mark64 from '../../assets/icons/mark-64.png?no-inline';
import mark96 from '../../assets/icons/mark-96.png?no-inline';
import { brandMarkProps } from './brandMarkSources.js';

const URLS = { 24: mark24, 32: mark32, 48: mark48, 64: mark64, 96: mark96 };

/** The crystal J emblem, decorative (alt=""), at 24, 32 or 48 CSS px with a 2x source. */
export default function BrandMark({ size = 24, className = '' }) {
  return <img className={`brand-mark ${className}`.trim()} {...brandMarkProps(size, URLS)} />;
}
