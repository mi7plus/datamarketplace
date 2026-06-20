// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },
  modules: [
    '@nuxt/eslint',
    '@nuxtjs/tailwindcss',
    '@pinia/nuxt',
  ],
  css: ['~/assets/css/main.css'],
  app: {
    head: {
      title: 'Rowbound — The data clearing house',
      meta: [
        { name: 'description', content: 'Get exactly the data you need — buy it, request it, or collect it — and pay only for matching records.' },
        { name: 'theme-color', content: '#0F1E3D' },
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/brand/Rowbound_icon_tile.svg' },
        { rel: 'alternate icon', href: '/favicon.ico' },
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