/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: '#171717',
        muted: '#262626',
        surface: '#E5E5E5',
        canvas: '#FAFAFA',
      },
    },
  },
  plugins: [],
}

