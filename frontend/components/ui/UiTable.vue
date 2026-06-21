<script setup lang="ts">
defineProps<{ columns: string[] }>()
</script>

<template>
    <div class="overflow-x-auto border border-surface-border rounded-xl bg-white">
        <table class="w-full text-sm">
            <thead>
                <tr class="text-left border-b border-surface-border">
                    <th v-for="c in columns" :key="c"
                        class="px-3 py-2 font-medium text-surface-label uppercase text-xs tracking-wide">
                        {{ c }}
                    </th>
                </tr>
            </thead>
            <tbody class="divide-y divide-surface-border">
                <slot />
            </tbody>
        </table>
    </div>
</template>
