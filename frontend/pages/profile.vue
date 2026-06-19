<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useApi } from '~/composables/useApi'
import { useAuthStore } from '~/stores/auth'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import BackButton from '~/components/BackButton.vue'

definePageMeta({ middleware: 'auth' })

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const { post, get } = useApi()

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
const saved = ref(false)

// Reputation / analytics
const analytics = ref<any>(null)

// Stripe Connect state (providers only)
const stripeConnected = ref(false)
const stripeLoading = ref(false)
const stripeError = ref<string | null>(null)
const stripeAccountId = ref<string | null>(null)

const saveProfile = async () => {
  loading.value = true
  error.value = ''
  saved.value = false
  try {
    await post('/profile', form.value)
    saved.value = true
  } catch (err: any) {
    error.value = err.message || 'Failed to save'
  } finally {
    loading.value = false
  }
}

const loadProfile = async () => {
  try {
    const res = await get('/profile/')
    form.value = {
      firstName: res.firstName || '',
      lastName: res.lastName || '',
      companyName: res.companyName || '',
      email: res.email || '',
      phone: res.phone || '',
      address: res.address || '',
      user_type: res.user_type || 'person'
    }
  } catch (err) {
    console.error("Failed to load profile:", err)
  }
}

const loadStripeStatus = async () => {
  if (auth.user?.role !== 'provider') return
  try {
    const res = await get('/profile/stripe-status')
    stripeConnected.value = res.connected
  } catch { /* ignore */ }
}

const connectStripe = async () => {
  stripeLoading.value = true
  stripeError.value = null
  try {
    const res = await get('/profile/stripe-connect')
    stripeAccountId.value = res.stripe_account_id
    // Redirect to Stripe onboarding
    window.location.href = res.url
  } catch (e: any) {
    stripeError.value = e.message || 'Failed to start Connect onboarding'
  } finally {
    stripeLoading.value = false
  }
}

async function loadAnalytics() {
  if (!auth.user?.id) return
  try {
    const res = await get(`/reviews/user/${auth.user.id}`)
    analytics.value = res
  } catch { /* ignore */ }
}

onMounted(async () => {
  await loadProfile()
  await Promise.all([loadStripeStatus(), loadAnalytics()])

  // Show a banner if returning from Stripe Connect
  const stripeParam = route.query.stripe as string
  if (stripeParam === 'success') {
    stripeConnected.value = true
  }
})

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

      <!-- Error / success -->
      <p v-if="error" class="text-red-500 text-sm">{{ error }}</p>
      <p v-if="saved" class="text-green-600 text-sm">Profile saved.</p>

      <!-- Submit -->
      <button
          type="submit"
          :disabled="loading"
          class="bg-black text-white px-6 py-3 rounded mt-4 w-full"
      >
        {{ loading ? 'Saving...' : 'Save Profile' }}
      </button>
    </form>

    <!-- ====== Reputation ====== -->
    <div v-if="analytics" class="mt-8 border rounded-lg p-5 bg-white">
      <h2 class="text-xl font-semibold mb-3">Reputation</h2>
      <div class="flex items-center gap-4">
        <div class="text-4xl font-bold text-yellow-500">
          {{ analytics.average_rating?.toFixed(1) ?? '—' }}
        </div>
        <div class="text-sm text-gray-500">
          <div class="flex gap-0.5 text-xl">
            <span v-for="n in 5" :key="n"
              :class="n <= Math.round(analytics.average_rating ?? 0) ? 'text-yellow-400' : 'text-gray-200'">★</span>
          </div>
          <div>{{ analytics.review_count }} review{{ analytics.review_count !== 1 ? 's' : '' }}</div>
        </div>
      </div>
      <div v-if="analytics.reviews?.length" class="mt-4 space-y-3 max-h-64 overflow-y-auto">
        <div v-for="r in analytics.reviews" :key="r.id"
          class="border rounded p-3 text-sm space-y-1">
          <div class="flex items-center gap-2">
            <span class="text-yellow-400">{{ '★'.repeat(r.rating) }}<span class="text-gray-200">{{ '★'.repeat(5 - r.rating) }}</span></span>
            <span class="text-xs text-gray-400">{{ r.created_at ? new Date(r.created_at).toLocaleDateString() : '' }}</span>
          </div>
          <p v-if="r.comment" class="text-gray-600">{{ r.comment }}</p>
        </div>
      </div>
    </div>

    <!-- ====== Stripe Connect (providers only) ====== -->
    <div v-if="auth.user?.role === 'provider'" class="mt-10 border rounded-lg p-6 bg-white">
      <h2 class="text-xl font-semibold mb-1">Payouts</h2>
      <p class="text-gray-500 text-sm mb-4">
        Connect a Stripe account to receive payments when your submissions are accepted.
      </p>

      <div v-if="stripeConnected" class="flex items-center gap-2 text-green-700 text-sm">
        <span class="text-lg">✓</span>
        <span>Stripe account connected. You'll receive payouts automatically.</span>
      </div>

      <div v-else>
        <p v-if="stripeError" class="text-red-500 text-sm mb-3">{{ stripeError }}</p>
        <button
          @click="connectStripe"
          :disabled="stripeLoading"
          class="bg-indigo-600 text-white px-5 py-2.5 rounded hover:bg-indigo-700 disabled:opacity-50 text-sm">
          {{ stripeLoading ? 'Redirecting to Stripe…' : 'Connect with Stripe' }}
        </button>
        <p class="text-xs text-gray-400 mt-2">
          You'll be taken to Stripe's hosted onboarding — no banking details enter our app.
        </p>
      </div>
    </div>
  </PageWrapper>
</template>