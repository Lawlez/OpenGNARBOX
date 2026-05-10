/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
    "./services/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'SF Mono'", "'Fira Code'", "'Cascadia Code'", "'JetBrains Mono'",
               "'Consolas'", "'Monaco'", "'Menlo'", "'Courier New'", 'monospace'],
        mono: ["'SF Mono'", "'Fira Code'", "'Cascadia Code'", "'JetBrains Mono'",
               "'Consolas'", "'Monaco'", "'Menlo'", "'Courier New'", 'monospace'],
      },
      colors: {
        gray: {
          750: '#2d3748',
          850: '#1a202c',
          950: '#0d1117',
        }
      }
    }
  },
  plugins: [],
}
