<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
    <div class="text-center py-12 px-6 border border-dashed border-surface-border rounded-xl bg-white">
        <h3 class="font-wordmark text-lg text-ink">{{ title }}</h3>
        <p v-if="description" class="text-sm text-muted mt-1 max-w-md mx-auto">{{ description }}</p>
        <div class="mt-4"><slot /></div>
    </div>
</template>
