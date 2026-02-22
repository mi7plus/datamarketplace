<script setup>
import { useRoute, useRouter } from 'vue-router'
const route = useRoute()
const router = useRouter()
import { useAuthStore } from '@/stores/auth'
const auth = useAuthStore()
const logout = async () => {
  auth.logout()
  await router.push('/login')
}
const linkClass = (path) =>
    route.path.startsWith(path)
        ? 'text-black font-semibold'
        : 'text-gray-600 hover:text-black'
</script>

<template>
  <header class="bg-white border-b sticky top-0 z-50">
    <div class="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
      <NuxtLink to="/" class="text-xl font-bold">
        Data Exchange
      </NuxtLink>

      <nav class="flex items-center gap-6">
        <NuxtLink v-if="auth.isAuthenticated" to="/requests" :class="linkClass('/requests')">
          Browse Requests
        </NuxtLink>

        <NuxtLink v-if="auth.isAuthenticated" to="/requests/create" :class="linkClass('/requests/create')">
          Post Request
        </NuxtLink>

        <NuxtLink v-if="auth.isAuthenticated" to="/submissions" :class="linkClass('/submissions')" class="text-gray-600 hover:text-black">
          My Submissions
        </NuxtLink>
        <NuxtLink v-if="auth.isAuthenticated" to="/profile" :class="linkClass('/profile')" class="text-gray-600 hover:text-black">
          My Profile
        </NuxtLink>
        <NuxtLink v-if="!auth.isAuthenticated" to="/login">Login</NuxtLink>
        <NuxtLink v-if="!auth.isAuthenticated" to="/register">Register</NuxtLink>
        <button v-if="auth.isAuthenticated" @click="logout" class="text-gray-600 hover:text-black">
          Logout
        </button>
      </nav>
    </div>
  </header>
</template>