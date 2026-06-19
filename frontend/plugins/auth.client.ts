import { useAuthStore } from '~/stores/auth'

// Rehydrate the session on app start: if there's no in-memory access token
// (e.g. after a full page reload), silently mint one from the httpOnly refresh
// cookie. Best-effort — a failed refresh just means the user is logged out.
// This plugin is async, so Nuxt awaits it before route middleware runs, so a
// reload of a protected page won't bounce to /login before the token is restored.
export default defineNuxtPlugin(async () => {
    const auth = useAuthStore()
    if (!auth.token) await auth.refresh()
})
