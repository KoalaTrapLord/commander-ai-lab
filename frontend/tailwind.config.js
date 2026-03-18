/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          base: '#12141e',
          zone: '#1c2034',
          panel: '#161820',
          bar: '#1a1e30',
          phase: '#1e2338',
          hand: '#1a2030',
        },
        accent: {
          blue: '#3c82dc',
          think: '#64b4ff',
          purple: '#7060c0',
        },
        life: {
          high: '#50c87a',
          med: '#dcb432',
          low: '#dc3c3c',
        },
        seat: {
          0: '#4696ff',
          1: '#ff6450',
          2: '#50d278',
          3: '#dcaa32',
        },
        card: {
          bg: '#2a3050',
          hand: '#2a3868',
          selected: '#3a4878',
        },
        border: {
          zone: '#3a4060',
          sep: '#2a2e48',
          btn: '#4060a0',
          overlay: '#4060c0',
          'btn-hover': '#6080d0',
          'btn-primary': '#4080d0',
          'hand-card': '#5060a0',
          chip: '#444444',
        },
        phase: {
          tab: '#252a42',
          text: '#888888',
        },
        btn: {
          primary: '#2a5090',
        },
        text: {
          body: '#e8e8e8',
          muted: '#888888',
          system: '#555566',
          'zone-label': '#666666',
          status: '#777788',
          sub: '#aaaaaa',
          btn: '#cccccc',
        },
        highlight: {
          gold: '#ffdc32',
          commander: '#ffd200',
        },
      },
      keyframes: {
        pulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
      },
      animation: {
        pulse: 'pulse 1s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
