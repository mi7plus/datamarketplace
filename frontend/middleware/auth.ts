import { useAuthStore } from '~/stores/auth'

export default defineNuxtRouteMiddleware((to) => {
    if (process.server) return

    const auth = useAuthStore()

    const publicPages = ['/login', '/register']

    if (!auth.token && !publicPages.includes(to.path)) {
        return navigateTo('/login')
    }
})