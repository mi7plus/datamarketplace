export default defineNuxtPlugin(() => {
    const auth = useAuthStore()

    async function refreshIfNeeded() {
        if (!auth.token) return

        try {
            const res = await fetch(
                '/auth/refresh',
                { credentials: 'include' }
            )

            if (res.ok) {
                const data = await res.json()
                auth.setToken(data.access_token)
            }
            else {
                auth.logout()
            }
        }
        catch {
            auth.logout()
        }
    }

    setInterval(refreshIfNeeded, 5 * 60 * 1000)
})