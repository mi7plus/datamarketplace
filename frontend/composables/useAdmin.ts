import { useApi } from '~/composables/useApi'

// Admin identity + capabilities, fetched once from GET /admin/me and cached for the
// session. `can(cap)` drives which Tier-2 action controls render. The backend
// independently enforces every capability — this is UX gating, not the security
// boundary (design §5: never rely on hiding UI client-side).
export interface AdminMe {
  id: string
  email: string
  admin_role: string | null
  mfa_enabled: boolean
  capabilities: string[]
}

export const useAdmin = () => {
  const me = useState<AdminMe | null>('admin-me', () => null)

  const loadAdmin = async (): Promise<AdminMe | null> => {
    if (me.value) return me.value
    try {
      me.value = await useApi().get('/admin/me')
    } catch {
      me.value = null   // 403 = not an admin
    }
    return me.value
  }

  const can = (cap: string) => !!me.value?.capabilities?.includes(cap)

  return { me, loadAdmin, can }
}
