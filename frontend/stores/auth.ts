import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
    state: () => ({
        // Access token lives ONLY in memory (never localStorage) so XSS can't
        // exfiltrate it. It is re-minted from the httpOnly refresh cookie on reload.
        token: null as string | null,
        refreshing: false,
        user: null as { id: string; email: string; role?: string } | null,
    }),

    getters: {
        isAuthenticated: (state) => !!state.token,
    },

    actions: {
        setToken(token: string) {
            this.token = token
        },

        setUser(user: { id: string; email: string; role?: string }) {
            this.user = user
        },

        clear() {
            this.token = null
            this.user = null
        },

        async login(email: string, password: string) {
            const base = useRuntimeConfig().public.apiBase
            const res: any = await $fetch(base + '/auth/login', {
                method: 'POST',
                body: { email, password },
                credentials: 'include',      // let the backend set the httpOnly refresh cookie
            })
            this.setToken(res.access_token)
        },

        async register(email: string, password: string, role: string = 'requester') {
            const base = useRuntimeConfig().public.apiBase
            const res = await $fetch(base + '/auth/register', {
                method: 'POST',
                body: { email, password, role },
                credentials: 'include',
            })
            // Log the user in automatically after registration
            await this.login(email, password)
            return res
        },

        // Mint a fresh access token from the httpOnly refresh cookie.
        // Returns true on success; clears state and returns false on failure.
        async refresh(): Promise<boolean> {
            const base = useRuntimeConfig().public.apiBase
            try {
                const res: any = await $fetch(base + '/auth/refresh', {
                    method: 'GET',
                    credentials: 'include',   // sends the httpOnly refresh cookie
                })
                this.setToken(res.access_token)
                return true
            } catch {
                this.clear()
                return false
            }
        },

        // FE5 enhances this to invalidate the server-side refresh token.
        async logout() {
            this.clear()
            await navigateTo('/login')
        },
    },
})
