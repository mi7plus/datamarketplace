<script setup lang="ts">
withDefaults(defineProps<{ accent?: boolean; padded?: boolean }>(), { padded: true })
</script>

<template>
    <div class="bg-white rounded-xl border"
        :class="[accent ? 'border-accent' : 'border-surface-border', padded ? 'p-5' : '']">
        <slot />
    </div>
</template>
