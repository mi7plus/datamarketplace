<script setup lang="ts">
// Renders social-login buttons for ONLY the providers the backend currently has
// configured (GET /auth/oauth/providers). A provider whose creds aren't injected in
// the running API simply doesn't appear — no dead button that 404s. The OR divider
// shows only when there's at least one provider.
import GoogleButton from '~/components/auth/GoogleButton.vue'
import MicrosoftButton from '~/components/auth/MicrosoftButton.vue'

const apiBase = useRuntimeConfig().public.apiBase
const { data } = await useFetch<{ configured: string[] }>(`${apiBase}/auth/oauth/providers`)
const configured = computed(() => data.value?.configured ?? [])
</script>

<template>
  <div v-if="configured.length">
    <GoogleButton v-if="configured.includes('google')" class="mb-3" />
    <MicrosoftButton v-if="configured.includes('microsoft')" class="mb-3" />
    <div class="flex items-center gap-3 mb-4 text-xs text-gray-400">
      <span class="flex-1 border-t"></span>OR<span class="flex-1 border-t"></span>
    </div>
  </div>
</template>
