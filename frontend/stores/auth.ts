import { defineStore } from 'pinia'
import { useRouter } from 'vue-router'

export const useAuthStore = defineStore('auth', {
    state: () => ({
        token: null as string | null,
        refreshing: false,
        user: null
    }),

    getters: {
        isAuthenticated: (state) => !!state.token
    },

    actions: {

        init() {
            if (process.client) {
                this.token = localStorage.getItem('token')
            }
        },

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
            const res = await $fetch(base + '/auth/register', {
                method: 'POST',
                body: { email, password, role }
            })
            // Optionally, log the user in automatically after registration
            await this.login(email, password)
            return res
        },

        logout() {
            this.token = null
            this.user = null

            if (process.client) {
                localStorage.removeItem('token')
            }

            navigateTo('/login')
        },

        setToken(token: string) {
            this.token = token
            this.user = null

            if (process.client) {
                localStorage.setItem('token', token)
            }
        },

        setUser(user: { id: string; email: string }) {
            this.user = user
        },

        clear() {
            this.token = null
            this.user = null
            if (process.client) {
                localStorage.removeItem('token')
            }
        }
    }
})