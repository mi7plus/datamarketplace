// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },
  modules: [
    '@nuxt/eslint',
    '@nuxtjs/tailwindcss',
    '@pinia/nuxt',
    '@nuxt/content',
  ],
  css: ['~/assets/css/main.css'],
  // Baseline security headers on every route (S6). A full strict CSP needs the
  // nuxt-security module + nonces to avoid breaking Nuxt hydration — tracked as
  // a follow-up; these non-breaking headers land now.
  routeRules: {
    '/**': {
      headers: {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Referrer-Policy': 'no-referrer',
      },
    },
  },
  app: {
    head: {
      title: 'Rowbound — The data clearing house',
      meta: [
        { name: 'description', content: 'Get exactly the data you need — buy it, request it, or collect it — and pay only for matching records.' },
        { name: 'theme-color', content: '#0F1E3D' },
        { property: 'og:site_name', content: 'Rowbound' },
        { property: 'og:type', content: 'website' },
        { property: 'og:image', content: '/brand/Rowbound_icon_tile.svg' },
        { name: 'twitter:card', content: 'summary' },
        { name: 'twitter:image', content: '/brand/Rowbound_icon_tile.svg' },
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/brand/Rowbound_icon_tile.svg' },
        { rel: 'alternate icon', href: '/favicon.ico' },
      ],
      script: [
        {
          type: 'application/ld+json',
          innerHTML: JSON.stringify({
            '@context': 'https://schema.org',
            '@type': 'Organization',
            name: 'Rowbound',
            description: 'The data clearing house — buy, request, or collect data through one funded, escrowed, per-record settlement engine.',
            slogan: 'The data clearing house',
          }),
        },
      ],
    },
  },
  // Pre-render marketing + guides for crawlability and speed (SSG); the app
  // routes stay SSR/SPA. crawlLinks off so it won't wander into app pages that
  // need the backend. Client-only auth plugins don't run during prerender.
  // Pre-render marketing + guides for SEO/speed in normal prod builds. NOTE: the
  // site-gate (server/middleware/site-gate) covers all SSR routes + everything in
  // `npm run dev`; prerendered static pages here are public brochure content and are
  // the one thing the gate doesn't cover in a prod build. For a fully-gated staging
  // build, build with PRERENDER_MARKETING=false to SSR everything.
  nitro: {
    // Pin the Amplify SSR preset so the compute function is built correctly
    // regardless of whether Amplify sets NITRO_PRESET (an unset/wrong preset
    // produces a handler Amplify can't invoke → 502).
    preset: 'aws-amplify',
    // Disable prerendering when the private-preview gate is active (SITE_PASSWORD set)
    // or when PRERENDER_MARKETING=false. Prerendered pages are static HTML served by
    // the CDN, so the site-gate server middleware never runs for them — leaving the
    // homepage/guides ungated. SSR-only keeps every route going through the middleware.
    prerender: (process.env.SITE_PASSWORD || process.env.PRERENDER_MARKETING === 'false')
      ? undefined
      : {
          crawlLinks: false,
          routes: [
            '/', '/about', '/contact', '/terms', '/privacy', '/guides',
            '/guides/how-to-write-a-good-data-request',
            '/guides/how-escrow-and-settlement-works',
            '/guides/selling-data-on-rowbound',
            '/guides/licensing-and-provenance',
            '/guides/your-data-and-gdpr',
            '/guides/partial-fulfilment-and-cross-mode',
          ],
        },
  },
  runtimeConfig: {
    // Private: only available on server-side
    apiSecret: process.env.API_SECRET || '',

    // Public: available in both client and server
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:3001'
    }
  }
})