<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useApi } from '~/composables/useApi'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'

// Reactive form state
const router = useRouter()
const form = ref({
  firstName: '',
  lastName: '',
  companyName: '',
  email: '',
  phone: '',
  address: '',
  user_type: 'person'
})
const loading = ref(false)
const error = ref('')
const { post } = useApi()

const saveProfile = async () => {
  try {
    const res = await post('/profile', form.value)
    console.log('Profile saved', res)
  } catch (err) {
    console.error(err)
  }
}
</script>

<template>
  <PageWrapper class="max-w-3xl mx-auto px-6 py-12">
    <BackButton fallback="/" />
    <h1 class="text-3xl font-bold mb-6">Complete Your Profile</h1>

    <!-- User type selector -->
    <div class="mb-6 flex gap-4">
      <button
          :class="form.user_type === 'person' ? 'bg-black text-white' : 'bg-gray-200'"
          class="px-4 py-2 rounded"
          @click="form.user_type = 'person'"
      >
        Individual
      </button>
      <button
          :class="form.user_type === 'company' ? 'bg-black text-white' : 'bg-gray-200'"
          class="px-4 py-2 rounded"
          @click="form.user_type = 'company'"
      >
        Company
      </button>
    </div>

    <form @submit.prevent="saveProfile" class="space-y-4">
      <!-- Individual fields -->
      <div v-if="form.user_type === 'person'" class="space-y-4">
        <div>
          <label class="block text-sm font-medium">First Name</label>
          <input v-model="form.firstName" type="text" required class="w-full border px-3 py-2 rounded" />
        </div>
        <div>
          <label class="block text-sm font-medium">Last Name</label>
          <input v-model="form.lastName" type="text" required class="w-full border px-3 py-2 rounded" />
        </div>
      </div>

      <!-- Company fields -->
      <div v-if="form.user_type === 'company'">
        <label class="block text-sm font-medium">Company Name</label>
        <input v-model="form.companyName" type="text" required class="w-full border px-3 py-2 rounded" />
      </div>

      <!-- Common fields -->
      <div>
        <label class="block text-sm font-medium">Email</label>
        <input v-model="form.email" type="email" required class="w-full border px-3 py-2 rounded" />
      </div>
      <div>
        <label class="block text-sm font-medium">Phone</label>
        <input v-model="form.phone" type="tel" class="w-full border px-3 py-2 rounded" />
      </div>
      <div>
        <label class="block text-sm font-medium">Address</label>
        <input v-model="form.address" type="text" class="w-full border px-3 py-2 rounded" />
      </div>

      <!-- Error message -->
      <p v-if="error" class="text-red-500">{{ error }}</p>

      <!-- Submit -->
      <button
          type="submit"
          :disabled="loading"
          class="bg-black text-white px-6 py-3 rounded mt-4 w-full"
      >
        {{ loading ? 'Saving...' : 'Save Profile' }}
      </button>
    </form>
  </PageWrapper>
</template>