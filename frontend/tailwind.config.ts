import type { Config } from 'tailwindcss'

// Rowbound brand tokens (from Rowbound_Logo.svg logo system).
export default <Partial<Config>>{
  theme: {
    extend: {
      colors: {
        ink: '#0F1E3D',          // primary / structure
        accent: '#2DD4BF',       // teal — active/settlement states
        'accent-deep': '#14B8A6',
        muted: '#64748B',
        surface: '#F8FAFC',      // page background
        'surface-border': '#E2E8F0',
        'surface-label': '#94A3B8',
      },
      fontFamily: {
        // Wordmark / logotype + headings use the serif; body/UI stays sans.
        wordmark: ['Georgia', "'Times New Roman'", 'serif'],
      },
    },
  },
}
