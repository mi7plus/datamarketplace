import { defineContentConfig, defineCollection, z } from '@nuxt/content'

export default defineContentConfig({
    collections: {
        guides: defineCollection({
            type: 'page',
            source: 'guides/**/*.md',
            schema: z.object({
                title: z.string(),
                description: z.string().optional(),
                order: z.number().optional(),
                audience: z.string().optional(),   // buyers | suppliers | all
            }),
        }),
    },
})
