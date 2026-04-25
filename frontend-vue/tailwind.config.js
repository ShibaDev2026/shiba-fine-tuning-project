/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surface（深炭系）
        surface: {
          0: '#0a0c0f',
          1: '#111318',
          2: '#191d24',
          3: '#21262f',
          4: '#2c333e',
          5: '#3a4454',
        },
        // Text
        'txt-primary':   '#edf0f4',
        'txt-secondary': '#8a97a8',
        'txt-muted':     '#505c6e',
        'txt-inverse':   '#111318',
        // Brand / Silver
        silver: {
          light: '#dce6ee',
          mid:   '#a8b8c8',
          dark:  '#6e8098',
        },
        // Tech Accent
        accent: {
          cyan:     '#06c8e8',
          'cyan-dim': '#033848',
          teal:     '#10b981',
          indigo:   '#6366f1',
        },
        // Routing
        local:  '#f5c518',
        claude: '#c084fc',
        // Status
        success:     '#00e676',
        'success-dim': '#00251a',
        warning:     '#ffab40',
        'warning-dim': '#2c1800',
        error:       '#ff5252',
        'error-dim':   '#2c0000',
        info:        '#40c4ff',
        'info-dim':    '#00293d',
        // Layer accents
        layer: {
          0: '#f5c518',
          1: '#40c4ff',
          2: '#c084fc',
          3: '#ffab40',
        },
      },
      fontFamily: {
        display: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Display"', '"Noto Sans TC"', 'sans-serif'],
        body:    ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Text"', '"Noto Sans TC"', '"Source Han Sans TC"', 'sans-serif'],
        mono:    ['"SF Mono"', '"IBM Plex Mono"', '"Fira Code"', 'monospace'],
      },
      fontSize: {
        'xs':   '11px',
        'sm':   '12px',
        'base': '13px',
        'md':   '14px',
        'lg':   '16px',
        'xl':   '20px',
        '2xl':  '24px',
        '3xl':  '32px',
      },
      borderRadius: {
        sm:   '5px',
        md:   '8px',
        lg:   '12px',
        xl:   '16px',
        full: '9999px',
      },
      boxShadow: {
        card:   '0 2px 8px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.04)',
        panel:  '0 8px 32px rgba(0,0,0,0.7)',
        silver: '0 1px 3px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.08)',
      },
    },
  },
  plugins: [],
}
