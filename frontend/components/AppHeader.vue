<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const open = ref(false)
const close = () => { open.value = false }
const logout = async () => {
  close()
  auth.logout()
  await router.push('/login')
}

// Single source of truth for the nav, rendered in both the desktop row and the
// mobile panel so they can't drift.
const links = computed(() => {
  const l = [
    { to: '/', label: 'Get data', exact: true },
    { to: '/catalog', label: 'Catalog' },
    { to: '/collect', label: 'Collect' },
  ]
  if (auth.isAuthenticated) {
    l.push(
      { to: '/requests', label: 'Browse Requests' },
      { to: '/requests/create', label: 'Post Request' },
      { to: '/submissions', label: 'My Submissions' },
      { to: '/purchases', label: 'My Purchases' },
      { to: '/profile', label: 'My Profile' },
    )
  }
  return l
})

const isActive = (link) => (link.exact ? route.path === link.to : route.path.startsWith(link.to))
const linkClass = (link) =>
  isActive(link) ? 'text-ink font-semibold' : 'text-muted hover:text-ink transition-colors'

// Always close the mobile menu after navigating.
watch(() => route.path, close)
</script>

<template>
  <header class="bg-white border-b sticky top-0 z-50">
    <div class="max-w-6xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between">
      <NuxtLink to="/" class="flex items-center gap-2.5" aria-label="Rowbound home">
        <img src="/brand/Rowbound_icon_tile.svg" alt="" class="h-8 w-8" />
        <span class="font-wordmark text-2xl font-bold text-ink tracking-tight">Rowbound</span>
      </NuxtLink>

      <!-- Desktop nav -->
      <nav class="hidden md:flex items-center gap-6">
        <NuxtLink v-for="link in links" :key="link.to" :to="link.to" :class="linkClass(link)">
          {{ link.label }}
        </NuxtLink>
        <template v-if="auth.isAuthenticated">
          <button @click="logout" class="text-muted hover:text-ink transition-colors">Logout</button>
        </template>
        <template v-else>
          <NuxtLink to="/login" :class="linkClass({ to: '/login' })">Login</NuxtLink>
          <NuxtLink
            to="/register"
            class="bg-ink text-white px-3 py-1.5 rounded-lg hover:opacity-90 transition-opacity"
          >
            Register
          </NuxtLink>
        </template>
      </nav>

      <!-- Mobile burger -->
      <button
        class="md:hidden inline-flex items-center justify-center h-10 w-10 -mr-2 rounded-lg text-ink hover:bg-surface transition-colors"
        :aria-expanded="open"
        aria-controls="mobile-menu"
        aria-label="Toggle navigation menu"
        @click="open = !open"
      >
        <svg v-if="!open" class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
        <svg v-else class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>

    <!-- Mobile menu panel -->
    <nav
      v-show="open"
      id="mobile-menu"
      class="md:hidden border-t bg-white px-4 py-3 flex flex-col gap-1"
    >
      <NuxtLink
        v-for="link in links"
        :key="link.to"
        :to="link.to"
        class="block px-2 py-2.5 rounded-lg hover:bg-surface"
        :class="linkClass(link)"
        @click="close"
      >
        {{ link.label }}
      </NuxtLink>

      <template v-if="auth.isAuthenticated">
        <button
          class="text-left px-2 py-2.5 rounded-lg text-muted hover:text-ink hover:bg-surface transition-colors"
          @click="logout"
        >
          Logout
        </button>
      </template>
      <template v-else>
        <NuxtLink to="/login" class="block px-2 py-2.5 rounded-lg text-muted hover:text-ink hover:bg-surface" @click="close">
          Login
        </NuxtLink>
        <NuxtLink
          to="/register"
          class="mt-1 text-center bg-ink text-white px-3 py-2.5 rounded-lg hover:opacity-90 transition-opacity"
          @click="close"
        >
          Register
        </NuxtLink>
      </template>
    </nav>
  </header>
</template>
