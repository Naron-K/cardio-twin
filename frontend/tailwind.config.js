/** @type {import('tailwindcss').Config} */

// ── "Scientific Indie" design tokens (see DESIGN.md) ──────────────────────────
// Only *extends* the default theme so the existing analysis/streaming views keep
// working with their slate-* classes.  The game UI uses the tokens below.
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#081425',
          lowest:  '#040e1f',
          low:     '#111c2d',
          mid:     '#152031',
          high:    '#1f2a3c',
          highest: '#2a3548',
          bright:  '#2f3a4c',
        },
        ink: {
          DEFAULT: '#d8e3fb',
          variant: '#e8bcbb',
        },
        line: {
          DEFAULT: '#ae8787',
          dim:     '#5e3f3e',
        },
        // Primary — Crimson Red (the pulse)
        crimson: {
          DEFAULT:   '#ffb3b3',
          on:        '#680014',
          container: '#ff525f',
          strong:    '#bf002e',
          deep:      '#920021',
          darkest:   '#5b0011',
          fixed:     '#ffdad9',
        },
        // Secondary — Oxygenated Blue (the flow)
        oxy: {
          DEFAULT:   '#bdf4ff',
          on:        '#00363d',
          container: '#00e3fd',
          dim:       '#00daf3',
          strong:    '#00616d',
          deep:      '#004f58',
          fixed:     '#9cf0ff',
        },
        warn: {
          DEFAULT: '#ffd8a8',
          strong:  '#f0a13c',
          deep:    '#6b3d00',
        },
        danger: {
          DEFAULT:   '#ffb4ab',
          container: '#93000a',
          on:        '#690005',
        },
      },
      fontFamily: {
        display: ['Sora', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        body:    ['"Hanken Grotesk"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono:    ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      // Named radii instead of overriding the default scale — keeps the older
      // views untouched while giving the game UI DESIGN.md's rounding.
      borderRadius: {
        card: '1rem',
        el:   '0.5rem',
      },
      boxShadow: {
        bloom:         '0 0 24px 0 rgb(255 82 95 / 0.30)',
        'bloom-sm':    '0 0 8px 0 rgb(255 82 95 / 0.35)',
        oxybloom:      '0 0 24px 0 rgb(0 227 253 / 0.30)',
        'oxybloom-sm': '0 0 8px 0 rgb(0 227 253 / 0.35)',
        inset1:        'inset 0 0 0 1px rgb(255 255 255 / 0.10)',
      },
      spacing: {
        gutter: '24px',
        margin: '32px',
      },
    },
  },
  plugins: [],
}
