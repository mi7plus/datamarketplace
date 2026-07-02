<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useApi } from '~/composables/useApi'
import { useAdmin } from '~/composables/useAdmin'
import { useToast } from '~/composables/useToast'
import AdminShell from '~/components/admin/AdminShell.vue'

definePageMeta({ middleware: ['admin'] })

const route = useRoute()
const id = route.params.id as string
const { can, me } = useAdmin()
const toast = useToast()

const user = ref<any>(null)
const activity = ref<any>(null)
const error = ref('')

const load = async () => {
  try {
    user.value = await useApi().get(`/admin/users/${id}`)
    activity.value = await useApi().get(`/admin/users/${id}/activity`)
  } catch (e: any) {
    error.value = e.message
  }
}
onMounted(load)

// Run a Tier-2 action: prompt for a required reason, and — when the acting admin has
// MFA on — a step-up TOTP code for sensitive actions. Sends X-MFA-Code so the backend
// step-up check passes.
const act = async (path: string, label: string, stepUp = false, extra: any = {}) => {
  const reason = window.prompt(`${label} — reason (recorded in the audit log):`, '')
  if (reason === null) return
  const headers: Record<string, string> = {}
  if (stepUp && me.value?.mfa_enabled) {
    const code = window.prompt('Enter your current MFA code to authorize:')
    if (!code) return
    headers['X-MFA-Code'] = code
  }
  try {
    await useApi().post(`/admin/${path}`, { reason, ...extra }, headers)
    toast.success(`${label} done`)
    await load()
  } catch (e: any) {
    toast.error(e.message || 'Action failed')
  }
}

const setRole = async () => {
  const role = window.prompt('Admin role (super_admin / support_lead / support_agent / read_only, or blank to revoke):', '')
  if (role === null) return
  await act(`users/${id}/admin-role`, 'Change admin role', true, { admin_role: role || null })
}
</script>

<template>
  <AdminShell>
    <NuxtLink to="/admin/users" class="text-sm text-teal-700 hover:underline">← Users</NuxtLink>
    <p v-if="error" class="text-red-600 my-4">{{ error }}</p>

    <div v-if="user" class="mt-3">
      <h1 class="text-2xl font-bold">{{ user.email }}</h1>
      <div class="flex flex-wrap gap-2 mt-2 text-xs">
        <span class="bg-gray-100 px-2 py-0.5 rounded">role: {{ user.role }}</span>
        <span class="bg-gray-100 px-2 py-0.5 rounded">admin: {{ user.admin_role || '—' }}</span>
        <span class="bg-gray-100 px-2 py-0.5 rounded">verified: {{ user.is_verified }}</span>
        <span class="bg-gray-100 px-2 py-0.5 rounded">MFA: {{ user.mfa_enabled }}</span>
        <span class="bg-gray-100 px-2 py-0.5 rounded">locked: {{ user.account_locked }}</span>
        <span class="bg-gray-100 px-2 py-0.5 rounded">suspended: {{ user.suspended }}</span>
      </div>

      <!-- Tier-2 actions, shown only for capabilities this admin holds -->
      <div class="mt-5 flex flex-wrap gap-2">
        <button v-if="can('user.unlock') && (user.account_locked || user.failed_login_attempts)"
                @click="act(`users/${id}/unlock`, 'Unlock account')"
                class="px-3 py-1.5 text-sm rounded bg-amber-600 text-white hover:bg-amber-700">Unlock</button>
        <button v-if="can('user.suspend') && !user.suspended && !user.admin_role"
                @click="act(`users/${id}/suspend`, 'Suspend account')"
                class="px-3 py-1.5 text-sm rounded bg-red-600 text-white hover:bg-red-700">Suspend</button>
        <button v-if="can('user.suspend') && user.suspended"
                @click="act(`users/${id}/reactivate`, 'Reactivate account')"
                class="px-3 py-1.5 text-sm rounded bg-green-600 text-white hover:bg-green-700">Reactivate</button>
        <button v-if="can('user.verify_resend') && !user.is_verified"
                @click="act(`users/${id}/resend-verification`, 'Resend verification')"
                class="px-3 py-1.5 text-sm rounded bg-gray-700 text-white hover:bg-gray-800">Resend verification</button>
        <button v-if="can('user.mfa_reset') && user.mfa_enabled"
                @click="act(`users/${id}/reset-mfa`, 'Reset MFA', true)"
                class="px-3 py-1.5 text-sm rounded bg-gray-700 text-white hover:bg-gray-800">Reset MFA</button>
        <button v-if="can('admin.manage')"
                @click="setRole"
                class="px-3 py-1.5 text-sm rounded border border-teal-600 text-teal-700 hover:bg-teal-50">Change admin role</button>
      </div>

      <!-- Activity -->
      <div v-if="activity" class="mt-8 grid md:grid-cols-2 gap-6">
        <section>
          <h2 class="font-semibold mb-2">Requests ({{ activity.requests.length }})</h2>
          <ul class="text-sm space-y-1">
            <li v-for="r in activity.requests" :key="r.id" class="bg-white rounded shadow-sm p-2">
              {{ r.title }} — <span class="text-gray-500">{{ r.status }}</span>
            </li>
            <li v-if="!activity.requests.length" class="text-gray-400">None</li>
          </ul>
        </section>
        <section>
          <h2 class="font-semibold mb-2">Submissions ({{ activity.submissions.length }})</h2>
          <ul class="text-sm space-y-1">
            <li v-for="s in activity.submissions" :key="s.id" class="bg-white rounded shadow-sm p-2 flex justify-between">
              <span>{{ s.status }}<span v-if="s.quarantined" class="text-red-600"> · quarantined</span></span>
              <button v-if="can('dataset.quarantine')"
                      @click="act(`submissions/${s.id}/${s.quarantined ? 'unquarantine' : 'quarantine'}`, s.quarantined ? 'Release quarantine' : 'Quarantine dataset')"
                      class="text-xs text-teal-700 hover:underline">
                {{ s.quarantined ? 'Release' : 'Quarantine' }}
              </button>
            </li>
            <li v-if="!activity.submissions.length" class="text-gray-400">None</li>
          </ul>
        </section>
        <section>
          <h2 class="font-semibold mb-2">Purchases ({{ activity.purchases.length }})</h2>
          <ul class="text-sm space-y-1">
            <li v-for="p in activity.purchases" :key="p.id" class="bg-white rounded shadow-sm p-2">
              {{ p.amount }} — <span class="text-gray-500">{{ p.status }}</span>
            </li>
            <li v-if="!activity.purchases.length" class="text-gray-400">None</li>
          </ul>
        </section>
        <section>
          <h2 class="font-semibold mb-2">Disputes ({{ activity.disputes.length }})</h2>
          <ul class="text-sm space-y-1">
            <li v-for="d in activity.disputes" :key="d.id" class="bg-white rounded shadow-sm p-2">
              {{ d.reason }} — <span class="text-gray-500">{{ d.status }}</span>
            </li>
            <li v-if="!activity.disputes.length" class="text-gray-400">None</li>
          </ul>
        </section>
      </div>
    </div>
  </AdminShell>
</template>
