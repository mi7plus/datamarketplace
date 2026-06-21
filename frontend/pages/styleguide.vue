<script setup lang="ts">
import { ref } from 'vue'
import { useToast } from '~/composables/useToast'

useHead({ title: 'Style guide — Rowbound' })

const toast = useToast()
const text = ref('')
const choice = ref('buyer')
const modalOpen = ref(false)

const swatches = [
    { name: 'Ink', var: 'bg-ink', hex: '#0F1E3D' },
    { name: 'Accent', var: 'bg-accent', hex: '#2DD4BF' },
    { name: 'Accent deep', var: 'bg-accent-deep', hex: '#14B8A6' },
    { name: 'Muted', var: 'bg-muted', hex: '#64748B' },
    { name: 'Surface', var: 'bg-surface border border-surface-border', hex: '#F8FAFC' },
]
const requestStates = ['draft', 'open', 'partially_fulfilled', 'completed', 'expired']
const subStates = ['validated', 'accepted', 'partially_accepted', 'paid', 'disputed']
</script>

<template>
    <div class="space-y-12 max-w-4xl">
        <header>
            <h1 class="font-wordmark text-3xl font-bold text-ink">Rowbound style guide</h1>
            <p class="text-muted mt-1">One visual language — serif for display, sans for UI.</p>
        </header>

        <section>
            <h2 class="font-wordmark text-xl text-ink mb-3">Palette</h2>
            <div class="flex flex-wrap gap-4">
                <div v-for="s in swatches" :key="s.name" class="text-xs">
                    <div class="h-16 w-28 rounded-lg" :class="s.var" />
                    <div class="mt-1 font-medium text-ink">{{ s.name }}</div>
                    <div class="text-surface-label">{{ s.hex }}</div>
                </div>
            </div>
        </section>

        <section>
            <h2 class="font-wordmark text-xl text-ink mb-3">Buttons</h2>
            <div class="flex flex-wrap gap-3 items-center">
                <UiButton variant="primary">Primary</UiButton>
                <UiButton variant="accent">Accent</UiButton>
                <UiButton variant="ghost">Ghost</UiButton>
                <UiButton variant="danger">Danger</UiButton>
                <UiButton variant="primary" disabled>Disabled</UiButton>
            </div>
        </section>

        <section>
            <h2 class="font-wordmark text-xl text-ink mb-3">Status pills</h2>
            <p class="text-sm text-muted mb-2">Requests</p>
            <div class="flex flex-wrap gap-2 mb-3">
                <UiStatusPill v-for="s in requestStates" :key="s" :status="s" />
            </div>
            <p class="text-sm text-muted mb-2">Submissions &amp; escrow</p>
            <div class="flex flex-wrap gap-2">
                <UiStatusPill v-for="s in subStates" :key="s" :status="s" />
                <UiStatusPill status="held" />
                <UiStatusPill status="released" />
            </div>
        </section>

        <section>
            <h2 class="font-wordmark text-xl text-ink mb-3">Form controls</h2>
            <div class="grid sm:grid-cols-2 gap-4 max-w-xl">
                <UiInput label="Email" type="email" placeholder="you@org.com" hint="We never share it." />
                <UiInput label="With error" error="This field is required" />
                <UiSelect label="Reason" v-model="choice"
                    :options="[{ value: 'buyer', label: 'Buyer' }, { value: 'supplier', label: 'Supplier' }]" />
                <UiTextarea label="Message" v-model="text" placeholder="Tell us more…" />
            </div>
        </section>

        <section>
            <h2 class="font-wordmark text-xl text-ink mb-3">Cards, badges, tooltip</h2>
            <div class="grid sm:grid-cols-2 gap-4">
                <UiCard>
                    <h3 class="font-medium text-ink">Default card</h3>
                    <p class="text-sm text-muted mt-1">Calm, bordered surface.</p>
                    <div class="mt-3 flex gap-2">
                        <UiBadge tone="accent">accent</UiBadge>
                        <UiBadge tone="ink">ink</UiBadge>
                        <UiBadge>neutral</UiBadge>
                    </div>
                </UiCard>
                <UiCard accent>
                    <h3 class="font-medium text-ink">Accent card</h3>
                    <UiTooltip text="Settlement state">
                        <span class="text-sm text-accent-deep underline decoration-dotted">hover me</span>
                    </UiTooltip>
                </UiCard>
            </div>
        </section>

        <section>
            <h2 class="font-wordmark text-xl text-ink mb-3">Table &amp; empty state</h2>
            <UiTable :columns="['Record', 'Source', 'Status']" class="mb-4">
                <tr>
                    <td class="px-3 py-2">acme-001</td>
                    <td class="px-3 py-2"><UiStatusPill status="catalog" /></td>
                    <td class="px-3 py-2"><UiStatusPill status="paid" /></td>
                </tr>
            </UiTable>
            <UiEmptyState title="Nothing here yet" description="When data arrives it shows up here.">
                <UiButton variant="accent" size="sm">Do something</UiButton>
            </UiEmptyState>
        </section>

        <section>
            <h2 class="font-wordmark text-xl text-ink mb-3">Toast &amp; modal</h2>
            <div class="flex gap-3">
                <UiButton variant="ghost" @click="toast.success('Settled — escrow released')">Toast success</UiButton>
                <UiButton variant="ghost" @click="toast.error('Something went wrong')">Toast error</UiButton>
                <UiButton variant="primary" @click="modalOpen = true">Open modal</UiButton>
            </div>
            <UiModal :open="modalOpen" title="Confirm release" @close="modalOpen = false">
                <p class="text-sm text-muted">Release escrow to the supplier for the accepted records?</p>
                <div class="mt-4 flex justify-end gap-2">
                    <UiButton variant="ghost" size="sm" @click="modalOpen = false">Cancel</UiButton>
                    <UiButton variant="accent" size="sm" @click="modalOpen = false">Confirm</UiButton>
                </div>
            </UiModal>
        </section>
    </div>
</template>
