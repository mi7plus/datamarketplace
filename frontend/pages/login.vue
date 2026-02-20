<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '~/stores/auth'
import { useRouter } from 'vue-router'
import PageWrapper from '~/components/layout/PageWrapper.vue'

const auth = useAuthStore()
const router = useRouter()

const email = ref('')
const password = ref('')

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