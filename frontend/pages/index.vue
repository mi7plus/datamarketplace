<script setup lang="ts">
import PageWrapper from '~/components/layout/PageWrapper.vue'

useHead({
    title: 'Rowbound — the data clearing house',
    meta: [
        { name: 'description', content: 'Get exactly the data you need — buy it, request it, or collect it — through one funded, escrowed, per-record settlement engine.' },
        { property: 'og:title', content: 'Rowbound — the data clearing house' },
        { property: 'og:description', content: 'Buy it, request it, or collect it. Pay only for matching records.' },
        { property: 'og:type', content: 'website' },
    ],
})

const problems = [
    { h: "Can't get what you need", p: 'Catalogs are browse-and-hope. No funded, structured way to say "I need this — here\'s the money."' },
    { h: 'Trust gaps stall deals', p: "Buyers can't verify before paying; suppliers fear delivering before they're paid. Deals die in diligence." },
    { h: 'Suppliers fly blind', p: 'Listing and hoping is a weak go-to-market. Real demand is invisible to the people who could fill it.' },
    { h: 'No market for new data', p: "When the data doesn't exist yet, buyers fall back on costly managed vendors or DIY collection." },
]
const modes = [
    { h: 'Buy existing', p: 'Suppliers pre-list datasets; buyers purchase any portion, priced per record.', tag: 'Live' },
    { h: 'Request', p: 'Buyers specify and pre-fund exactly what they need; suppliers compete to fill it.', tag: 'Live' },
    { h: 'Collect', p: "Buyers commission fresh field data via structured forms, gathered by suppliers' own teams.", tag: 'Live' },
]
const whyNow = [
    { n: '$29B', p: "Scale AI's valuation after Meta took a 49% stake — which sent Google & OpenAI toward neutral suppliers." },
    { n: '$10B', p: "Mercor's valuation 8 months after Scale's client flight — proof demand is in motion." },
    { n: '−99%', p: "Appen's stock from its peak — the commodity-labeling model squeezed by synthetic & in-house data." },
]
const buyerSteps = [
    'Post a request: schema, unique key, quantity, license, budget.',
    'Fund it — your budget is held in escrow, not spent.',
    'Accept matching records; pay per record, the rest is refunded.',
]
const supplierSteps = [
    'List a dataset or accept a funded request / collection.',
    'Deliver; the buyer verifies the full file before release.',
    'Get paid per accepted record, settled from escrow.',
]
const trust = [
    ['Funded escrow', 'Budget is held up front — proof the buyer is real, protection the supplier can trust.'],
    ['Verify before release', 'Buyers inspect the full file during an acceptance window before any money moves.'],
    ['Per-record settlement', 'Pay only for matching records that pass validation — never the whole file on faith.'],
    ['Cross-source dedup', 'No record is paid for twice, even when a request is filled from several suppliers.'],
    ['Per-record provenance & license', 'Source, license and consent basis travel with every delivered record.'],
    ['Neutral by design', 'Unconflicted by any buyer or cloud — infrastructure, not a competitor.'],
]
</script>

<template>
    <PageWrapper class="space-y-20 py-6">
        <!-- 1 · HERO (reversed lockup on ink) -->
        <section class="rounded-3xl bg-ink text-white px-6 sm:px-12 py-16 sm:py-20 relative overflow-hidden">
            <div class="absolute -right-16 -top-16 w-72 h-72 rounded-full bg-white/5" aria-hidden="true" />
            <div class="relative max-w-3xl">
                <img src="/brand/Rowbound_logo_reversed.svg" alt="Rowbound" class="h-10 mb-8" />
                <h1 class="font-wordmark text-4xl sm:text-5xl font-bold leading-tight">
                    Get exactly the data you need — buy it, request it, or collect it.
                </h1>
                <p class="mt-4 text-lg text-white/80">Pay only for matching records.</p>
                <p class="mt-2 text-sm uppercase tracking-widest text-accent">The data clearing house</p>
                <div class="mt-8 flex flex-wrap gap-3">
                    <UiButton to="/requests/create" variant="accent" size="lg">Post a data request</UiButton>
                    <NuxtLink to="/register"
                        class="inline-flex items-center justify-center text-base px-6 py-3 rounded-lg border border-white/30 text-white hover:border-accent transition-colors">
                        Become a supplier
                    </NuxtLink>
                </div>
            </div>
        </section>

        <!-- 2 · PROBLEM -->
        <section>
            <p class="text-xs uppercase tracking-widest text-accent-deep mb-2">The problem</p>
            <h2 class="font-wordmark text-3xl font-bold text-ink mb-8">Buying external data is slow, fragmented, and low-trust</h2>
            <div class="grid sm:grid-cols-2 gap-5">
                <UiCard v-for="p in problems" :key="p.h">
                    <h3 class="font-wordmark text-lg font-bold text-ink">{{ p.h }}</h3>
                    <p class="text-sm text-muted mt-2">{{ p.p }}</p>
                </UiCard>
            </div>
        </section>

        <!-- 3 · THREE WAYS, ONE ENGINE -->
        <section>
            <p class="text-xs uppercase tracking-widest text-accent-deep mb-2">The solution</p>
            <h2 class="font-wordmark text-3xl font-bold text-ink mb-8">Three ways to get data — one settlement engine</h2>
            <div class="grid md:grid-cols-3 gap-5">
                <UiCard v-for="m in modes" :key="m.h" accent>
                    <div class="flex items-center justify-between">
                        <h3 class="font-wordmark text-xl font-bold text-ink">{{ m.h }}</h3>
                        <UiBadge tone="accent">{{ m.tag }}</UiBadge>
                    </div>
                    <p class="text-sm text-muted mt-2">{{ m.p }}</p>
                </UiCard>
            </div>
            <div class="mt-5 rounded-xl bg-ink text-white px-6 py-5">
                <p class="font-wordmark text-accent italic mb-2">…or any mix of the three against one request</p>
                <p class="text-sm text-white/85">
                    <span class="font-semibold">Funded escrow</span> · per-record settlement ·
                    <span class="font-semibold">concurrency-safe allocation</span> ·
                    <span class="font-semibold">cross-source dedup</span>
                </p>
            </div>
        </section>

        <!-- 4 · WHY IT'S DIFFERENT — cross-mode diagram (the moat) -->
        <section>
            <p class="text-xs uppercase tracking-widest text-accent-deep mb-2">Why it's different</p>
            <h2 class="font-wordmark text-3xl font-bold text-ink mb-8">Cross-mode fulfilment — what no incumbent can do</h2>
            <div class="grid lg:grid-cols-[1.1fr_auto_1fr_auto_1fr] gap-4 items-stretch">
                <div class="rounded-xl bg-ink text-white p-5">
                    <p class="text-xs uppercase tracking-widest text-accent mb-2">One funded request</p>
                    <p class="text-sm text-white/85">Schema · quantity · unique key · license · budget, with money held in escrow.</p>
                </div>
                <div class="hidden lg:flex items-center text-surface-label text-2xl">→</div>
                <div class="space-y-3">
                    <div class="rounded-lg border border-surface-border bg-white px-4 py-3 text-sm text-ink">Existing catalog rows</div>
                    <div class="rounded-lg border border-surface-border bg-white px-4 py-3 text-sm text-ink">Freshly collected rows</div>
                    <div class="rounded-lg border border-surface-border bg-white px-4 py-3 text-sm text-ink">Commissioned rows</div>
                </div>
                <div class="hidden lg:flex items-center text-surface-label text-2xl">→</div>
                <div class="grid grid-rows-2 gap-3">
                    <div class="rounded-xl bg-accent text-ink p-5 font-wordmark font-bold flex items-center">Dedup + allocation + escrow</div>
                    <div class="rounded-xl bg-ink text-white p-5">
                        <p class="font-wordmark font-bold">One clean, deduped dataset</p>
                        <p class="text-xs text-accent mt-1">Pay only per matching record</p>
                    </div>
                </div>
            </div>
            <p class="text-sm text-muted italic mt-6 max-w-3xl">
                No catalog, discovery tool, or managed vendor fills one request from a deduplicated blend of all
                three supply modes. That allocation + dedup logic is the IP and the moat.
            </p>
        </section>

        <!-- 5 · WHY NOW -->
        <section>
            <p class="text-xs uppercase tracking-widest text-accent-deep mb-2">Why now</p>
            <h2 class="font-wordmark text-3xl font-bold text-ink mb-8">The market is moving toward neutral, commissioned data</h2>
            <div class="grid sm:grid-cols-3 gap-5">
                <UiCard v-for="w in whyNow" :key="w.n">
                    <div class="font-wordmark text-4xl font-bold text-ink">{{ w.n }}</div>
                    <p class="text-sm text-muted mt-3">{{ w.p }}</p>
                </UiCard>
            </div>
            <p class="text-sm text-ink font-medium italic mt-6 max-w-3xl">
                Value is shifting from commodity labeling to proprietary, commissioned, real-world data — and
                buyers want neutral, non-conflicted supply.
            </p>
        </section>

        <!-- 6 · HOW IT WORKS -->
        <section>
            <p class="text-xs uppercase tracking-widest text-accent-deep mb-2">How it works</p>
            <h2 class="font-wordmark text-3xl font-bold text-ink mb-8">Built for both sides</h2>
            <div class="grid md:grid-cols-2 gap-5">
                <UiCard>
                    <h3 class="font-wordmark text-lg font-bold text-ink mb-3">For buyers</h3>
                    <ol class="space-y-2">
                        <li v-for="(s, i) in buyerSteps" :key="i" class="flex gap-3 text-sm text-muted">
                            <span class="font-wordmark font-bold text-accent-deep">{{ i + 1 }}</span><span>{{ s }}</span>
                        </li>
                    </ol>
                </UiCard>
                <UiCard>
                    <h3 class="font-wordmark text-lg font-bold text-ink mb-3">For suppliers</h3>
                    <ol class="space-y-2">
                        <li v-for="(s, i) in supplierSteps" :key="i" class="flex gap-3 text-sm text-muted">
                            <span class="font-wordmark font-bold text-accent-deep">{{ i + 1 }}</span><span>{{ s }}</span>
                        </li>
                    </ol>
                </UiCard>
            </div>
        </section>

        <!-- 7 · TRUST & SECURITY -->
        <section>
            <p class="text-xs uppercase tracking-widest text-accent-deep mb-2">Trust &amp; security</p>
            <h2 class="font-wordmark text-3xl font-bold text-ink mb-8">A money product, built like one</h2>
            <div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
                <UiCard v-for="t in trust" :key="t[0]">
                    <h3 class="font-medium text-ink">{{ t[0] }}</h3>
                    <p class="text-sm text-muted mt-1">{{ t[1] }}</p>
                </UiCard>
            </div>
            <p class="text-sm text-muted mt-5">
                See exactly how it works in the
                <NuxtLink to="/guides/how-escrow-and-settlement-works" class="text-accent-deep hover:underline">escrow &amp; settlement guide</NuxtLink>.
            </p>
        </section>

        <!-- 8 / 9 · DUAL PATH + FINAL CTA -->
        <section class="grid md:grid-cols-2 gap-5">
            <div class="rounded-2xl bg-ink text-white p-8">
                <h3 class="font-wordmark text-2xl font-bold">For buyers</h3>
                <p class="text-sm text-white/80 mt-2">Post exactly what you need and fund it. Pay only for matching records.</p>
                <UiButton to="/requests/create" variant="accent" class="mt-5">Post a data request</UiButton>
            </div>
            <div class="rounded-2xl border border-surface-border bg-white p-8">
                <h3 class="font-wordmark text-2xl font-bold text-ink">For suppliers</h3>
                <p class="text-sm text-muted mt-2">List datasets, fill funded requests, or collect fresh field data — and get paid per record.</p>
                <UiButton to="/register" variant="primary" class="mt-5">Become a supplier</UiButton>
            </div>
        </section>
    </PageWrapper>
</template>
