// ESLint flat config: correctness rules only (no formatting or style rules).
// Scope: the React renderer (src/), the Electron host (electron/), the Node client
// tests (tests/*.mjs, tests/*.cjs), the Node QA/launch scripts (scripts/*.cjs) and the
// root build configs. Run with `npm run lint:js`.
//
// TypeScript (src/transport/**/*.ts, tests/types/**/*.ts) is not linted here: no
// ESLint TypeScript parser is installed, and `npm run check:types` (tsc --strict)
// already checks those files.
const js = require('@eslint/js');
const globals = require('globals');
const react = require('eslint-plugin-react');
const reactHooks = require('eslint-plugin-react-hooks');

const unusedVars = ['error', { args: 'after-used', ignoreRestSiblings: true, caughtErrors: 'none' }];

module.exports = [
  { ignores: ['dist/**', 'node_modules/**', '.runtime/**', '**/*.ts'] },
  {
    ...js.configs.recommended,
    rules: { ...js.configs.recommended.rules, 'no-unused-vars': unusedVars },
  },
  {
    // React renderer: browser ES modules with JSX.
    files: ['src/**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { react, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    rules: {
      // Only what stops JSX-referenced components and React counting as unused.
      'react/jsx-uses-vars': 'error',
      'react/jsx-uses-react': 'error',
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
  {
    // AudioWorklet processors run in the worklet global scope, not the window.
    files: ['src/**/*.worklet.js'],
    languageOptions: { globals: globals.audioWorklet },
  },
  {
    // Electron main/preload and the Node QA, launch and build scripts: CommonJS.
    files: ['electron/**/*.{js,cjs}', 'scripts/**/*.cjs', 'tests/**/*.cjs', '*.config.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'commonjs',
      globals: globals.node,
    },
  },
  {
    // The preload script also touches renderer globals (window, document).
    files: ['electron/preload.js'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  {
    // Node test runner suites and the ESM build config.
    files: ['tests/**/*.mjs', 'vite.config.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.node,
    },
  },
];
