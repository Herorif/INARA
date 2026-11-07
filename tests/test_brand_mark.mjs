import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { BRAND_MARK_SIZES, brandMarkProps } from '../src/shared/ui/brandMarkSources.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = name => fs.readFileSync(path.join(ROOT, name), 'utf8');
const URLS = { 24: 'm24.png', 32: 'm32.png', 48: 'm48.png', 64: 'm64.png', 96: 'm96.png' };

function pngSize(name) {
  const data = fs.readFileSync(path.join(ROOT, name));
  assert.equal(data.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', name);
  return [data.readUInt32BE(16), data.readUInt32BE(20)];
}

test('each mark size uses its own 1x file and the next file up as 2x', () => {
  assert.deepEqual(BRAND_MARK_SIZES, { 24: [24, 48], 32: [32, 64], 48: [48, 96] });
  for (const [size, one, two] of [[24, 'm24.png', 'm48.png'], [32, 'm32.png', 'm64.png'], [48, 'm48.png', 'm96.png']]) {
    assert.deepEqual(brandMarkProps(size, URLS), {
      src: one, srcSet: `${one} 1x, ${two} 2x`, width: size, height: size,
      alt: '', 'aria-hidden': 'true', draggable: 'false',
    });
  }
});

test('unsupported sizes and missing files are refused', () => {
  for (const size of [16, 20, 40, 64, 96, '24']) assert.throws(() => brandMarkProps(size, URLS), RangeError);
  assert.throws(() => brandMarkProps(32, { ...URLS, 64: undefined }), /mark-64\.png/);
});

test('the published mark files are the sizes their names say', () => {
  for (const size of [24, 32, 48, 64, 96]) assert.deepEqual(pngSize(`src/assets/icons/mark-${size}.png`), [size, size]);
});

test('BrandMark imports the five published marks', () => {
  const source = read('src/shared/ui/BrandMark.jsx');
  for (const size of [24, 32, 48, 64, 96]) {
    // Emitted files: an inlined data: 2x would always win Chromium's srcset choice.
    assert.match(source, new RegExp(`import mark${size} from '\\.\\./\\.\\./assets/icons/mark-${size}\\.png\\?no-inline';`));
  }
  assert.match(source, /const URLS = \{ 24: mark24, 32: mark32, 48: mark48, 64: mark64, 96: mark96 \};/);
  assert.match(source, /<img className=\{`brand-mark \$\{className\}`\.trim\(\)\} \{\.\.\.brandMarkProps\(size, URLS\)\} \/>/);
});

test('the title bar and quick assistant show the mark at their sizes', () => {
  const sites = [
    ['src/app/CommandDeck.jsx', 24, 'titlebar-brand brand"><BrandMark size={24} />'],
    ['src/app/QuickAssistant.jsx', 24, 'quick-header__brand"><BrandMark size={24} />'],
  ];
  for (const [name, size, context] of sites) {
    const source = read(name).replace(/\r\n/g, '\n');
    assert.ok(source.includes(context), `${name}: BrandMark ${size}`);
    assert.match(source, /import BrandMark from '\.\.\/shared\/ui\/BrandMark';/);
    assert.doesNotMatch(source, /monogram/);
  }
  // The empty conversation's welcome shows the live core instead (C1 speaking core).
  const conversation = read('src/app/Conversation.jsx');
  assert.doesNotMatch(conversation, /BrandMark|monogram/);
  assert.ok(conversation.replace(/\r\n/g, '\n').includes('conversation-welcome">\n                <PresenceRing className="conversation-hero-core" size={CORE_HERO}'));
});

test('the text monogram style is gone and the mark has no border', () => {
  const css = read('src/shared/ui/primitives.css');
  assert.doesNotMatch(css, /\.monogram/);
  const rule = css.match(/\.brand-mark \{([^}]*)\}/)[1];
  assert.doesNotMatch(rule, /border/);
  assert.match(rule, /flex-shrink: 0/);
  assert.match(read('src/app/conversation.css'), /\.conversation-welcome \.conversation-hero-core \{ margin-bottom: \.5rem; gap: 0; \}/);
});
