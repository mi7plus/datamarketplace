<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAuthStore } from '~/stores/auth'
import { useRoute, useRouter } from 'vue-router'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import GoogleButton from '~/components/auth/GoogleButton.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const email = ref('')
const password = ref('')

// Messages set by redirects back to /login (email verify + OAuth outcomes).
const notice = computed(() => {
  if (route.query.verified) return { kind: 'ok', text: 'Email verified — you can now sign in.' }
  if (route.query.error === 'unverified_email')
    return { kind: 'err', text: "That provider account's email isn't verified. Sign in another way." }
  if (route.query.error === 'oauth') return { kind: 'err', text: 'Social sign-in failed. Please try again.' }
  return null
})

const submit = async () => {
  try {
    await auth.login(email.value, password.value)
    router.push('/') // redirect after login
  } catch (err: any) {
    alert(err.data?.detail || 'Login failed')
  }
}
</script>

<template>

  <PageWrapper class="flex items-center justify-center bg-gray-50">
    <div class="w-full max-w-md p-8 bg-white shadow-md rounded-lg">
      <h1 class="text-2xl font-bold mb-6 text-center">Login</h1>

      <p
        v-if="notice"
        :class="notice.kind === 'ok' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'"
        class="mb-4 text-sm rounded px-3 py-2 text-center"
      >
        {{ notice.text }}
      </p>

      <GoogleButton class="mb-4" />
      <div class="flex items-center gap-3 mb-4 text-xs text-gray-400">
        <span class="flex-1 border-t"></span>OR<span class="flex-1 border-t"></span>
      </div>

      <form @submit.prevent="submit" class="flex flex-col gap-4">
        <input
            v-model="email"
            type="email"
            placeholder="Email"
            class="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <input
            v-model="password"
            type="password"
            placeholder="Password"
            class="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
            type="submit"
            class="bg-blue-600 text-white py-2 px-4 rounded hover:bg-blue-700 transition"
        >
          Login
        </button>
      </form>
      <p class="mt-4 text-center text-sm text-gray-500">
        Don’t have an account?
        <NuxtLink class="text-blue-600 hover:underline" to="/register">Register</NuxtLink>
      </p>
    </div>
  </PageWrapper>
</template>