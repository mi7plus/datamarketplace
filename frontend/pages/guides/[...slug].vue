<script setup lang="ts">
import PageWrapper from '~/components/layout/PageWrapper.vue'

const route = useRoute()
const { data: doc } = await useAsyncData(`guide-${route.path}`,
    () => queryCollection('guides').path(route.path).first())

if (!doc.value) {
    throw createError({ statusCode: 404, statusMessage: 'Guide not found', fatal: true })
}

useHead(() => ({
    title: doc.value ? `${doc.value.title} — Rowbound` : 'Guide — Rowbound',
    meta: [{ name: 'description', content: doc.value?.description ?? '' }],
}))
</script>

<template>
    <PageWrapper class="max-w-2xl py-6">
        <NuxtLink to="/guides" class="text-sm text-accent-deep hover:underline">← All guides</NuxtLink>
        <article v-if="doc" class="guide-prose mt-4">
            <h1 class="font-wordmark text-3xl font-bold text-ink mb-2">{{ doc.title }}</h1>
            <p v-if="doc.description" class="text-muted text-lg mb-6">{{ doc.description }}</p>
            <ContentRenderer :value="doc" />
        </article>
    </PageWrapper>
</template>
