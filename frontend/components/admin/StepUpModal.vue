<script setup lang="ts">
// In-app confirmation modal for admin (Tier-2) actions. Collects the required audit
// reason and, for sensitive actions when the admin has MFA on, a step-up TOTP code
// (sent as X-MFA-Code). Optionally shows an admin-role picker (grant/revoke).
import { ref, watch, computed, nextTick } from 'vue'

const props = defineProps<{
  open: boolean
  title: string
  description?: string
  danger?: boolean         // red confirm button for destructive actions
  requireCode?: boolean    // show + require the step-up MFA code
  roleSelect?: boolean     // show the admin-role picker
  confirmLabel?: string
}>()

const emit = defineEmits<{
  (e: 'confirm', payload: { reason: string; code: string; role: string | null }): void
  (e: 'cancel'): void
}>()

const reason = ref('')
const code = ref('')
const role = ref('')       // '' = revoke when roleSelect
const reasonEl = ref<HTMLTextAreaElement | null>(null)

const ROLES = [
  { value: '', label: '— none (revoke admin) —' },
  { value: 'read_only', label: 'READ_ONLY' },
  { value: 'support_agent', label: 'SUPPORT_AGENT' },
  { value: 'support_lead', label: 'SUPPORT_LEAD' },
  { value: 'super_admin', label: 'SUPER_ADMIN' },
]

// Reset + focus each time the modal opens.
watch(() => props.open, async (o) => {
  if (o) {
    reason.value = ''; code.value = ''; role.value = ''
    await nextTick(); reasonEl.value?.focus()
  }
})

const canConfirm = computed(() => {
  if (props.requireCode && code.value.trim().length < 6) return false
  return reason.value.trim().length > 0
})

const confirm = () => {
  if (!canConfirm.value) return
  emit('confirm', {
    reason: reason.value.trim(),
    code: code.value.trim(),
    role: props.roleSelect ? (role.value || null) : null,
  })
}
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
       @keydown.esc="emit('cancel')">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md p-6" role="dialog" aria-modal="true">
      <h3 class="text-lg font-semibold">{{ title }}</h3>
      <p v-if="description" class="text-sm text-gray-500 mt-1">{{ description }}</p>

      <div v-if="roleSelect" class="mt-4">
        <label class="block text-sm font-medium mb-1">Admin role</label>
        <select v-model="role" class="w-full border rounded px-3 py-2 focus:ring-2 focus:ring-teal-500 outline-none">
          <option v-for="r in ROLES" :key="r.value" :value="r.value">{{ r.label }}</option>
        </select>
      </div>

      <div class="mt-4">
        <label class="block text-sm font-medium mb-1">Reason <span class="text-gray-400">(recorded in the audit log)</span></label>
        <textarea ref="reasonEl" v-model="reason" rows="3"
                  class="w-full border rounded px-3 py-2 focus:ring-2 focus:ring-teal-500 outline-none"
                  placeholder="Why are you taking this action?"></textarea>
      </div>

      <div v-if="requireCode" class="mt-4">
        <label class="block text-sm font-medium mb-1">MFA code</label>
        <input v-model="code" inputmode="numeric" maxlength="6" placeholder="6-digit code"
               class="w-40 border rounded px-3 py-2 tracking-widest focus:ring-2 focus:ring-teal-500 outline-none"
               @keydown.enter="confirm" />
        <p class="text-xs text-gray-400 mt-1">This action is sensitive — re-enter your current authenticator code.</p>
      </div>

      <div class="mt-6 flex justify-end gap-2">
        <button class="px-4 py-2 rounded text-sm border hover:bg-gray-50" @click="emit('cancel')">Cancel</button>
        <button :disabled="!canConfirm"
                class="px-4 py-2 rounded text-sm text-white disabled:opacity-50"
                :class="danger ? 'bg-red-600 hover:bg-red-700' : 'bg-teal-600 hover:bg-teal-700'"
                @click="confirm">
          {{ confirmLabel || 'Confirm' }}
        </button>
      </div>
    </div>
  </div>
</template>
