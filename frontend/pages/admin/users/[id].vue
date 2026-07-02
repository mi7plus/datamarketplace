<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useApi } from '~/composables/useApi'
import { useAdmin } from '~/composables/useAdmin'
import { useToast } from '~/composables/useToast'
import AdminShell from '~/components/admin/AdminShell.vue'
import StepUpModal from '~/components/admin/StepUpModal.vue'

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

// A pending Tier-2 action awaiting confirmation in the modal.
const pending = ref<null | {
  path: string; title: string; description?: string; danger?: boolean
  sensitive?: boolean; roleSelect?: boolean
}>(null)
const submitting = ref(false)

// Sensitive actions (refund, MFA reset, admin-role) require a step-up code when the
// acting admin has MFA on — the modal collects it and we send X-MFA-Code.
const modalRequireCode = computed(() => !!pending.value?.sensitive && !!me.value?.mfa_enabled)

const openAction = (cfg: NonNullable<typeof pending.value>) => { pending.value = cfg }

const onConfirm = async (payload: { reason: string; code: string; role: string | null }) => {
  if (!pending.value) return
  submitting.value = true
  const headers: Record<string, string> = {}
  if (modalRequireCode.value && payload.code) headers['X-MFA-Code'] = payload.code
  const body: any = { reason: payload.reason }
  if (pending.value.roleSelect) body.admin_role = payload.role
  try {
    await useApi().post(`/admin/${pending.value.path}`, body, headers)
    toast.success('Done')
    pending.value = null
    await load()
  } catch (e: any) {
    toast.error(e.message || 'Action failed')
  } finally {
    submitting.value = false
  }
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
                @click="openAction({ path: `users/${id}/unlock`, title: 'Unlock account' })"
                class="px-3 py-1.5 text-sm rounded bg-amber-600 text-white hover:bg-amber-700">Unlock</button>
        <button v-if="can('user.suspend') && !user.suspended && !user.admin_role"
                @click="openAction({ path: `users/${id}/suspend`, title: 'Suspend account', danger: true, description: 'The account will be signed out and blocked from logging in.' })"
                class="px-3 py-1.5 text-sm rounded bg-red-600 text-white hover:bg-red-700">Suspend</button>
        <button v-if="can('user.suspend') && user.suspended"
                @click="openAction({ path: `users/${id}/reactivate`, title: 'Reactivate account' })"
                class="px-3 py-1.5 text-sm rounded bg-green-600 text-white hover:bg-green-700">Reactivate</button>
        <button v-if="can('user.verify_resend') && !user.is_verified"
                @click="openAction({ path: `users/${id}/resend-verification`, title: 'Resend verification email' })"
                class="px-3 py-1.5 text-sm rounded bg-gray-700 text-white hover:bg-gray-800">Resend verification</button>
        <button v-if="can('user.mfa_reset') && user.mfa_enabled"
                @click="openAction({ path: `users/${id}/reset-mfa`, title: 'Reset MFA', danger: true, sensitive: true, description: 'Clears the user\'s MFA so they must re-enroll. Account-recovery only.' })"
                class="px-3 py-1.5 text-sm rounded bg-gray-700 text-white hover:bg-gray-800">Reset MFA</button>
        <button v-if="can('admin.manage')"
                @click="openAction({ path: `users/${id}/admin-role`, title: 'Change admin role', sensitive: true, roleSelect: true, description: 'Grant or revoke this user\'s admin privileges.' })"
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
                      @click="openAction({ path: `submissions/${s.id}/${s.quarantined ? 'unquarantine' : 'quarantine'}`, title: s.quarantined ? 'Release quarantine' : 'Quarantine dataset' })"
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

    <StepUpModal
      :open="!!pending"
      :title="pending?.title || ''"
      :description="pending?.description"
      :danger="pending?.danger"
      :require-code="modalRequireCode"
      :role-select="pending?.roleSelect"
      :confirm-label="submitting ? 'Working…' : 'Confirm'"
      @confirm="onConfirm"
      @cancel="pending = null"
    />
  </AdminShell>
</template>
