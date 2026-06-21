<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import PageWrapper from '~/components/layout/PageWrapper.vue'
import { useApi } from '~/composables/useApi'
import { useToast } from '~/composables/useToast'

useHead({
    title: 'Contact — Rowbound',
    meta: [{ name: 'description', content: 'Talk to Rowbound — buyers, suppliers, press, and support.' }],
})

const api = useApi()
const toast = useToast()

const reasons = [
    { value: 'buyer', label: 'Buyer inquiry' },
    { value: 'supplier', label: 'Supplier / partner' },
    { value: 'press', label: 'Press' },
    { value: 'support', label: 'Support / other' },
]

const form = reactive({
    name: '', email: '', org: '', reason: 'buyer', message: '',
    consent: false, company_website: '',  // honeypot
})
const errors = reactive<Record<string, string>>({})
const submitting = ref(false)
const done = ref(false)
let startedAt = 0
onMounted(() => { startedAt = Date.now() })

function validate() {
    for (const k of Object.keys(errors)) delete errors[k]
    if (!form.name.trim()) errors.name = 'Required'
    if (!/.+@.+\..+/.test(form.email)) errors.email = 'Enter a valid email'
    if (!form.message.trim()) errors.message = 'Required'
    if (!form.consent) errors.consent = 'Please accept the privacy notice'
    return Object.keys(errors).length === 0
}

async function submit() {
    if (!validate()) return
    submitting.value = true
    try {
        await api.post('/contact/', {
            name: form.name, email: form.email, org: form.org || null,
            reason: form.reason, message: form.message, consent: form.consent,
            company_website: form.company_website,
            elapsed_ms: Date.now() - startedAt,
        })
        done.value = true
        toast.success("Thanks — we'll be in touch.")
    } catch (e: any) {
        toast.error(e.message || 'Could not send your message')
    } finally {
        submitting.value = false
    }
}
</script>

<template>
    <PageWrapper class="max-w-xl py-6">
        <h1 class="font-wordmark text-3xl font-bold text-ink">Contact us</h1>
        <p class="text-muted mt-1 mb-8">
            Whether you're buying, supplying, or just curious — pick a reason and we'll route it to the right place.
        </p>

        <UiEmptyState v-if="done" title="Message sent"
            description="Thanks for reaching out. We typically reply within two business days.">
            <UiButton to="/" variant="ghost" size="sm">Back to home</UiButton>
        </UiEmptyState>

        <form v-else class="space-y-4" @submit.prevent="submit">
            <UiSelect v-model="form.reason" label="Reason" :options="reasons" />
            <UiInput v-model="form.name" label="Name" required :error="errors.name" />
            <UiInput v-model="form.email" label="Email" type="email" required :error="errors.email" />
            <UiInput v-model="form.org" label="Organization" hint="Optional" />
            <UiTextarea v-model="form.message" label="Message" required :rows="5" :error="errors.message" />

            <!-- Honeypot: hidden from people, tempting to bots -->
            <div class="hidden" aria-hidden="true">
                <label>Company website<input v-model="form.company_website" tabindex="-1" autocomplete="off" /></label>
            </div>

            <label class="flex items-start gap-2 text-sm text-muted">
                <input type="checkbox" v-model="form.consent" class="mt-0.5" />
                <span>
                    I agree to Rowbound processing this message per the
                    <NuxtLink to="/privacy" class="text-accent-deep hover:underline">privacy policy</NuxtLink>.
                </span>
            </label>
            <p v-if="errors.consent" class="text-xs text-red-600">{{ errors.consent }}</p>

            <UiButton type="submit" variant="primary" :disabled="submitting">
                {{ submitting ? 'Sending…' : 'Send message' }}
            </UiButton>
            <p class="text-xs text-surface-label">We reply within ~2 business days.</p>
        </form>
    </PageWrapper>
</template>
