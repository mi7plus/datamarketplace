import { useAuthStore } from '~/stores/auth'
import { useAdmin } from '~/composables/useAdmin'

// Client-side admin guard. auth.client.ts has already re-minted the token from the
// refresh cookie before middleware runs, so auth.token is set for a logged-in user.
// A non-admin (GET /admin/me → 403) is bounced home. Defense in depth: every /admin
// API also enforces the capability server-side.
export default defineNuxtRouteMiddleware(async () => {
  if (import.meta.server) return
  const auth = useAuthStore()
  if (!auth.token) return navigateTo('/login')
  const me = await useAdmin().loadAdmin()
  if (!me) return navigateTo('/')
})
