import { FAMILIES, STOPS, SEMANTIC } from './scripts/build-tokens.mjs'

// Every colour family reads from a CSS variable (src/theme/tokens.css, generated
// from design/tokens.json). Light values equal Tailwind 3.4's defaults; `html.dark`
// swaps them, so existing classes like `bg-white/80` or `text-teal-700` theme
// themselves. `black` keeps Tailwind's default (overlays).
const v = (name) => `rgb(var(--c-${name}) / <alpha-value>)`

const colors = Object.fromEntries(
  FAMILIES.map((fam) => [fam, Object.fromEntries(STOPS.map((s) => [s, v(`${fam}-${s}`)]))]),
)
colors.white = v('white')
// Semantic names: bg-surface, bg-surface-raised, text-text, text-text-muted, border-border, bg-accent
for (const name of SEMANTIC) {
  if (name === 'accent') colors.accent.DEFAULT = v('accent')
  else colors[name] = v(name)
}

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans:    ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['Sora', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      colors,
    },
  },
  plugins: [],
}
