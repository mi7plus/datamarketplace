<script setup lang="ts">
defineProps<{ text: string }>()
</script>

<template>
    <span class="relative inline-flex group" tabindex="0">
        <slot />
        <span role="tooltip"
            class="pointer-events-none absolute left-1/2 -translate-x-1/2 bottom-full mb-1 z-50
                   whitespace-nowrap rounded bg-ink text-white text-xs px-2 py-1 opacity-0
                   group-hover:opacity-100 group-focus:opacity-100 transition-opacity">
            {{ text }}
        </span>
    </span>
</template>
