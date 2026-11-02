/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          50: '#f6f7f9',
          100: '#eceef2',
          200: '#d5d9e2',
          300: '#b0b8c7',
          400: '#8390a6',
          500: '#64718a',
          600: '#4d5872',
          700: '#3c455b',
          800: '#2b3243',
          900: '#1b2130',
          950: '#11151f',
        },
        accent: {
          50: '#eef4ff',
          100: '#dce7ff',
          200: '#bfd3ff',
          300: '#93b4ff',
          400: '#5f8cff',
          500: '#3a68f5',
          600: '#274bd8',
          700: '#213cae',
          800: '#203688',
          900: '#1f316d',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          '"Microsoft YaHei"',
          'sans-serif',
        ],
      },
      boxShadow: {
        card: '0 1px 2px rgba(17, 21, 31, 0.04), 0 4px 16px rgba(17, 21, 31, 0.04)',
      },
    },
  },
  plugins: [],
}
