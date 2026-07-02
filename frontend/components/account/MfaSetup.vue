<script setup lang="ts">
// Two-factor (TOTP) enrollment + status. Enroll → scan QR in an authenticator app
// (Google Authenticator, Authy, 1Password) → confirm a 6-digit code to activate.
// Required for admin-panel access when REQUIRE_ADMIN_MFA is on.
import { ref, onMounted } from 'vue'
import QRCode from 'qrcode'
import { useApi } from '~/composables/useApi'
import { useToast } from '~/composables/useToast'

const { get, post } = useApi()
const toast = useToast()

const enabled = ref<boolean | null>(null)   // null = loading
const enrolling = ref(false)
const secret = ref('')
const qrDataUrl = ref('')
const code = ref('')
const disabling = ref(false)
const busy = ref(false)

const loadStatus = async () => {
  try { enabled.value = (await get('/auth/mfa/status')).mfa_enabled }
  catch { enabled.value = false }
}
onMounted(loadStatus)

const startEnroll = async () => {
  busy.value = true
  try {
    const res = await post('/auth/mfa/enroll', {})
    secret.value = res.secret
    qrDataUrl.value = await QRCode.toDataURL(res.otpauth_uri)
    enrolling.value = true
  } catch (e: any) {
    toast.error(e.message || 'Could not start MFA setup')
  } finally { busy.value = false }
}

const confirmEnroll = async () => {
  busy.value = true
  try {
    await post('/auth/mfa/verify', { code: code.value.trim() })
    toast.success('MFA is now enabled')
    enrolling.value = false; code.value = ''; secret.value = ''; qrDataUrl.value = ''
    await loadStatus()
  } catch (e: any) {
    toast.error(e.message || 'Invalid code — try the current one')
  } finally { busy.value = false }
}

const disable = async () => {
  busy.value = true
  try {
    await post('/auth/mfa/disable', { code: code.value.trim() })
    toast.success('MFA disabled')
    disabling.value = false; code.value = ''
    await loadStatus()
  } catch (e: any) {
    toast.error(e.message || 'Invalid code')
  } finally { busy.value = false }
}
</script>

<template>
  <div class="mt-10 border rounded-lg p-6 bg-white">
    <h2 class="text-xl font-semibold mb-1">Two-factor authentication (MFA)</h2>
    <p class="text-gray-500 text-sm mb-4">
      Add a second step to sign-in with an authenticator app. Required for admin access.
    </p>

    <p v-if="enabled === null" class="text-gray-400 text-sm">Loading…</p>

    <!-- Enabled -->
    <div v-else-if="enabled && !disabling" class="flex items-center justify-between">
      <span class="flex items-center gap-2 text-green-700 text-sm"><span class="text-lg">✓</span> MFA is enabled.</span>
      <button class="text-sm text-red-600 hover:underline" @click="disabling = true">Disable</button>
    </div>

    <!-- Disabling: confirm with a code -->
    <div v-else-if="enabled && disabling" class="space-y-3">
      <p class="text-sm text-gray-600">Enter a current code to turn MFA off.</p>
      <input v-model="code" inputmode="numeric" placeholder="6-digit code"
             class="border rounded px-3 py-2 w-40 tracking-widest" />
      <div class="flex gap-2">
        <button :disabled="busy" class="bg-red-600 text-white px-4 py-2 rounded text-sm disabled:opacity-50" @click="disable">Confirm disable</button>
        <button class="px-4 py-2 rounded text-sm border" @click="disabling = false; code = ''">Cancel</button>
      </div>
    </div>

    <!-- Not enrolled yet -->
    <div v-else-if="!enrolling">
      <button :disabled="busy" class="bg-teal-600 text-white px-5 py-2.5 rounded hover:bg-teal-700 text-sm disabled:opacity-50" @click="startEnroll">
        {{ busy ? 'Starting…' : 'Set up MFA' }}
      </button>
    </div>

    <!-- Enrolling: show QR + confirm -->
    <div v-else class="space-y-4">
      <ol class="text-sm text-gray-600 list-decimal ml-5 space-y-1">
        <li>Scan this QR code in your authenticator app.</li>
        <li>Enter the 6-digit code it shows to finish.</li>
      </ol>
      <img v-if="qrDataUrl" :src="qrDataUrl" alt="MFA QR code" class="w-44 h-44 border rounded" />
      <p class="text-xs text-gray-400 break-all">
        Can't scan? Enter this key manually: <code class="text-gray-600">{{ secret }}</code>
      </p>
      <div class="flex gap-2 items-center">
        <input v-model="code" inputmode="numeric" placeholder="6-digit code"
               class="border rounded px-3 py-2 w-40 tracking-widest" />
        <button :disabled="busy" class="bg-teal-600 text-white px-4 py-2 rounded text-sm disabled:opacity-50" @click="confirmEnroll">
          {{ busy ? 'Verifying…' : 'Enable MFA' }}
        </button>
      </div>
    </div>
  </div>
</template>
