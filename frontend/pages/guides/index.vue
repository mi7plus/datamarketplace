<script setup lang="ts">
import PageWrapper from '~/components/layout/PageWrapper.vue'

useHead({
    title: 'Guides — Rowbound',
    meta: [{ name: 'description', content: 'Practical guides to funded requests, escrow & settlement, selling data, licensing, and cross-mode fulfilment.' }],
})

const { data: guides } = await useAsyncData('guides-index',
    () => queryCollection('guides').order('order', 'ASC').all())
</script>

<template>
    <PageWrapper class="max-w-3xl py-6">
        <h1 class="font-wordmark text-3xl font-bold text-ink">Guides</h1>
        <p class="text-muted mt-1 mb-8">
            How funded requests, escrow, per-record settlement, and cross-mode fulfilment actually work.
        </p>

        <div class="space-y-3">
            <NuxtLink v-for="g in guides" :key="g.path" :to="g.path"
                class="block border border-surface-border rounded-xl bg-white p-5 hover:border-accent transition-colors">
                <div class="flex items-center justify-between gap-3">
                    <h2 class="font-wordmark text-lg font-bold text-ink">{{ g.title }}</h2>
                    <UiBadge v-if="g.audience && g.audience !== 'all'" tone="accent">{{ g.audience }}</UiBadge>
                </div>
                <p v-if="g.description" class="text-sm text-muted mt-1">{{ g.description }}</p>
            </NuxtLink>
        </div>
    </PageWrapper>
</template>
