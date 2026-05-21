/** @type {import('tailwindcss').Config} */
export default {
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
      colors: {
        primary: {
          50:  '#f0fdfa', 100: '#ccfbf1',
          500: '#14b8a6', 600: '#0d9488',
          700: '#0f766e', 800: '#115e59', 900: '#134e4a',
        }
      }
    },
  },
  plugins: [],
}
