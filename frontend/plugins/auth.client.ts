import { useAuthStore } from '~/stores/auth'

export default defineNuxtPlugin(() => {
    const auth = useAuthStore()
    const token = localStorage.getItem('token')

    if (token) {
        auth.token = token
    }
})