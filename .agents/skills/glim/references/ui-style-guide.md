# GLiM Elite UI Standard 🎨

This guide defines the "Non-AI" aesthetic. Use these principles when the **Vibe** stat is low.

## 1. Typography
- **Primary:** Do NOT use Inter or System fonts. Default to Serif for headings (e.g., 'Playfair Display' or 'Instrument Serif') to create an editorial feel.
- **Scale:** Use a major third type scale. Large headers should be significantly larger than body text.

## 2. Layout & Spacing
- **Asymmetry:** Avoid perfectly centered blocks. Use CSS Grid to create offset layouts.
- **Negative Space:** Increase padding by 1.5x what you think is "normal." Let the elements breathe.
- **Subgrid:** Utilize CSS subgrid for card alignments to ensure perfect vertical rhythm.

## 3. Interaction Design
- **Micro-animations:** All buttons must have a subtle `cubic-bezier` transition on hover.
- **Borders:** Use thin, high-contrast borders (e.g., `1px solid rgba(0,0,0,0.1)`) instead of heavy shadows.
- **Glassmorphism:** Use `backdrop-filter: blur()` sparingly for overlays, never for main content.

## 4. Forbidden Elements
- No purple-to-blue gradients (The "SaaS" look).
- No generic 3D illustrations.
- No rounded corners greater than `12px`.
