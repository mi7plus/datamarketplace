import { useAuthStore } from '~/stores/auth'

// Proactively re-mint the access token every few minutes while logged in, so it
// rarely lapses mid-use. Delegates to the store's refresh() (correct apiBase +
// credentials); on failure refresh() clears state. The reactive 401-refresh-retry
// in useApi remains the authoritative recovery path.
export default defineNuxtPlugin(() => {
    const auth = useAuthStore()
    setInterval(() => {
        if (auth.token) auth.refresh()
    }, 5 * 60 * 1000)
})
