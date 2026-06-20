<script setup lang="ts">
// The "three ways to get data, one settlement engine" framing.
// Request is live; Buy existing and Collect are visible-but-coming surfaces.
const modes = [
  {
    key: 'request',
    title: 'Request',
    tag: 'Live',
    live: true,
    blurb: 'Post a bounty for the data you need. Providers fulfil it; you pay per matching record, capped at your budget.',
    to: '/requests/create',
    cta: 'Post a request',
  },
  {
    key: 'buy',
    title: 'Buy existing',
    tag: 'Live',
    live: true,
    blurb: 'Browse pre-listed datasets and purchase any portion, priced per record — settled through the same escrow.',
    to: '/catalog',
    cta: 'Browse catalog',
  },
  {
    key: 'collect',
    title: 'Collect',
    tag: 'Live',
    live: true,
    blurb: 'Commission fresh data gathered in the field by a provider’s own workforce — validated and settled per record.',
    to: '/collect',
    cta: 'Find collection work',
  },
]
</script>

<template>
  <section class="w-full max-w-5xl mx-auto">
    <p class="text-center text-surface-label text-xs tracking-widest uppercase mb-2">
      Three ways to get data · one settlement engine
    </p>
    <div class="grid md:grid-cols-3 gap-5 mt-6">
      <div v-for="m in modes" :key="m.key"
        class="rounded-xl border p-6 flex flex-col bg-white transition-colors"
        :class="m.live ? 'border-accent' : 'border-surface-border'">
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-wordmark text-xl font-bold text-ink">{{ m.title }}</h3>
          <span class="text-[11px] px-2 py-0.5 rounded-full font-medium"
            :class="m.live ? 'bg-accent/15 text-accent-deep' : 'bg-surface text-surface-label border border-surface-border'">
            {{ m.tag }}
          </span>
        </div>
        <p class="text-sm text-muted flex-1">{{ m.blurb }}</p>
        <NuxtLink v-if="m.live && m.to" :to="m.to"
          class="mt-5 inline-flex justify-center bg-ink text-white text-sm px-4 py-2 rounded-lg hover:bg-ink/90 transition-colors">
          {{ m.cta }}
        </NuxtLink>
        <span v-else
          class="mt-5 inline-flex justify-center text-sm px-4 py-2 rounded-lg border border-surface-border text-surface-label cursor-not-allowed select-none">
          {{ m.cta }}
        </span>
      </div>
    </div>
  </section>
</template>
