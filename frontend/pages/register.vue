<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '~/stores/auth'
import { useRouter } from 'vue-router'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import SocialLogins from '~/components/auth/SocialLogins.vue'

const auth = useAuthStore()
const router = useRouter()

const email = ref('')
const password = ref('')
const role = ref<'requester' | 'provider'>('requester') // Optional role selection

const submit = async () => {
  try {
    await auth.register(
      email.value,
      password.value,
      role.value,
    )
    alert('Registered successfully!')
    router.push('/') // redirect after registration
  } catch (err: any) {
    alert(err.data?.detail || 'Registration failed')
  }
}
</script>

<template>
  <PageWrapper class="flex items-center justify-center bg-gray-50">
    <div class="w-full max-w-md p-8 bg-white shadow-md rounded-lg">
      <h1 class="text-2xl font-bold mb-6 text-center">Register</h1>

      <SocialLogins />

      <form @submit.prevent="submit" class="flex flex-col gap-4">
        <input
            v-model="email"
            type="email"
            placeholder="Email"
            class="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            required
        />
        <input
            v-model="password"
            type="password"
            placeholder="Password"
            class="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            required
        />
        <select
            v-model="role"
            class="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="requester">Requester</option>
          <option value="provider">Provider</option>
        </select>
        <button
            type="submit"
            class="bg-green-600 text-white py-2 px-4 rounded hover:bg-green-700 transition"
        >
          Register
        </button>
      </form>
      <p class="mt-4 text-center text-sm text-gray-500">
        Already have an account?
        <NuxtLink class="text-blue-600 hover:underline" to="/login">Login</NuxtLink>
      </p>
    </div>
  </PageWrapper>
</template>