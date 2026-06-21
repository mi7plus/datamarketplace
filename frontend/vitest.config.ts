import { defineConfig } from 'vitest/config'

// Lightweight unit tests for pure frontend logic — no Nuxt runtime needed.
export default defineConfig({
    test: {
        include: ['tests/**/*.spec.ts'],
        environment: 'node',
    },
})
