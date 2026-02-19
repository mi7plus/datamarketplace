import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
    state: () => ({
        user: null as null | { id: string; email: string },
        token: ''
    }),
    actions: {
        login(user: { id: string; email: string }, token: string) {
            this.user = user
            this.token = token
        },
        logout() {
            this.user = null
            this.token = ''
        }
    }
})