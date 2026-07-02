<script setup lang="ts">
// Landing page for the social-login redirect. The backend has already set the
// httpOnly refresh cookie; we just mint the in-memory access token from it (same
// path as a page reload) and bounce to the app. The access token is never in the URL.
import { onMounted } from 'vue'
import { useAuthStore } from '~/stores/auth'
import { useRouter } from 'vue-router'
import PageWrapper from '~/components/layout/PageWrapper.vue'

// This page is only reachable mid-login; skip the auth guard so it can run.
definePageMeta({ middleware: [] })

const auth = useAuthStore()
const router = useRouter()

onMounted(async () => {
  const ok = await auth.refresh()
  router.replace(ok ? '/' : '/login?error=oauth')
})
</script>

<template>
  <PageWrapper class="flex items-center justify-center bg-gray-50">
    <p class="text-gray-500">Signing you in…</p>
  </PageWrapper>
</template>
