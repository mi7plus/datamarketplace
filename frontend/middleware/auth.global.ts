export default defineNuxtRouteMiddleware((to) => {
    const auth = useAuthStore()

    if (!auth.isAuthenticated && !['/login', '/register'].includes(to.path)) {
        return navigateTo('/login')
    }

    if (auth.isAuthenticated && ['/login', '/register'].includes(to.path)) {
        return navigateTo('/')
    }
})