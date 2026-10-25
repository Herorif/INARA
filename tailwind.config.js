/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            fontFamily: {
                // Mirrors --font-sans / --font-mono in src/app/tokens.css (fonts bundled via src/shared/ui/fonts.js).
                sans: ['"Inter Variable"', '"Segoe UI Variable"', '"Segoe UI"', 'system-ui', 'sans-serif'],
                mono: ['"JetBrains Mono Variable"', 'Consolas', 'ui-monospace', 'monospace'],
            },
            colors: {
                // Full scale anchored on the brand cyan (#70e0ed = 400). Hex keeps opacity modifiers working.
                cyan: {
                    50: '#effcfd',
                    100: '#d6f7fa',
                    200: '#b0eff5',
                    300: '#8ae8f2',
                    400: '#70e0ed',
                    500: '#4fcfdd',
                    600: '#34aebd',
                    700: '#2a8a96',
                    800: '#236a73',
                    900: '#1c4f56',
                    950: '#102f34',
                },
                // Semantic colors for new code; they follow the CSS variables in tokens.css.
                canvas: 'var(--bg-canvas)',
                panel: 'var(--bg-panel)',
                raised: 'var(--bg-raised)',
                overlay: 'var(--bg-overlay)',
                line: {
                    DEFAULT: 'var(--line)',
                    strong: 'var(--line-strong)',
                },
                ink: {
                    1: 'var(--text-1)',
                    2: 'var(--text-2)',
                    3: 'var(--text-3)',
                },
                accent: {
                    DEFAULT: 'var(--accent)',
                    hover: 'var(--accent-hover)',
                },
                ok: 'var(--ok)',
                warn: 'var(--warn)',
                danger: 'var(--danger)',
            },
        },
    },
    plugins: [],
}
