/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        fast:     '#3B82F6',
        emotion1: '#10B981',
        emotion2: '#F59E0B',
      },
    },
  },
  plugins: [],
}
