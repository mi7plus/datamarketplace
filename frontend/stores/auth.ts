import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
    state: () => ({
        token: null as string | null,
        user: null as any | null
    }),

    getters: {
        isAuthenticated: (state) => !!state.token
    },

    actions: {
        async login(email: string, password: string) {
            const config = useRuntimeConfig()
            const base = config.public.apiBase
            const res = await $fetch(base + '/auth/login', {
                method: 'POST',
                body: { email, password }
            })
            this.setToken(res.access_token)
        },

        async register(email: string, password: string, role: string = 'requester') {
            const config = useRuntimeConfig()
            const base = config.public.apiBase
            console.log(base)
            const res = await $fetch(base + '/auth/register', {
                method: 'POST',
                body: { email, password, role }
            })
            // Optionally, log the user in automatically after registration
            await this.login(email, password)
            return res
        },

        logout() {
            this.clear()
        },

        setToken(token: string) {
            this.token = token
            localStorage.setItem('token', this.token)
        },

        setUser(user: { id: string; email: string }) {
            this.user = user
        },

        clear() {
            this.token = null
            this.user = null
            localStorage.removeItem('token')
        }
    }
})