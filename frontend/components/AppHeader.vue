<script setup>
import { useRoute } from 'vue-router'
const route = useRoute()
import { useAuthStore } from '~/stores/auth'
const auth = useAuthStore()
// Initialize from localStorage safely (only on client)
if (process.client) {
  auth.initFromStorage?.()
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
        <NuxtLink v-if="auth.user" to="/requests" :class="linkClass('/requests')">
          Browse Requests
        </NuxtLink>

        <NuxtLink v-if="auth.user" to="/requests/create" :class="linkClass('/requests/create')">
          Post Request
        </NuxtLink>

        <NuxtLink v-if="auth.user" to="/submissions" class="text-gray-600 hover:text-black">
          My Submissions
        </NuxtLink>
        <NuxtLink v-if="!auth.user" to="/login">Login</NuxtLink>
        <NuxtLink v-if="!auth.user" to="/register">Register</NuxtLink>
        <button v-if="auth.user" @click="auth.logout" class="text-gray-600 hover:text-black">
          Logout
        </button>
      </nav>
    </div>
  </header>
</template>