<script setup lang="ts">
// "Continue with Microsoft" — full-page navigation to the backend OAuth start
// endpoint (work/school Entra accounts only). Same pattern as GoogleButton.
const apiBase = useRuntimeConfig().public.apiBase
const href = `${apiBase}/auth/oauth/microsoft/start`
</script>

<template>
  <a
    :href="href"
    class="flex items-center justify-center gap-3 w-full border border-gray-300 rounded px-4 py-2 bg-white hover:bg-gray-50 transition text-gray-700 font-medium"
  >
    <svg class="w-5 h-5" viewBox="0 0 23 23" aria-hidden="true">
      <path fill="#F25022" d="M1 1h10v10H1z"/>
      <path fill="#7FBA00" d="M12 1h10v10H12z"/>
      <path fill="#00A4EF" d="M1 12h10v10H1z"/>
      <path fill="#FFB900" d="M12 12h10v10H12z"/>
    </svg>
    Continue with Microsoft
  </a>
</template>
