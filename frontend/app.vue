<script setup>
import { useAuthStore } from '~/stores/auth'
import { onMounted } from 'vue'
const auth = useAuthStore()

onMounted(() => {
  // Example: Load token from localStorage
  const token = localStorage.getItem('token')
  if (token) {
    auth.setToken(token)
    // Optional: fetch user info from backend if needed
    // auth.setUser(...)
  }
})

</script>
<template>
  <div class="min-h-screen flex flex-col bg-gray-50">
    <!-- Header -->
    <AppHeader />

    <!-- Main content -->
    <main class="flex-1 max-w-6xl mx-auto p-6 w-full">
      <NuxtPage />
    </main>

    <!-- Footer -->
    <AppFooter />
  </div>
</template>