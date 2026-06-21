import { useState } from '#app'

export interface Toast {
    id: number
    message: string
    tone: 'success' | 'error' | 'info'
}

// Shared, SSR-safe toast queue.
export const useToasts = () => useState<Toast[]>('rb-toasts', () => [])

let _id = 0

export function useToast() {
    const toasts = useToasts()

    function push(message: string, tone: Toast['tone'] = 'info', ttl = 4000) {
        const id = ++_id
        toasts.value = [...toasts.value, { id, message, tone }]
        if (import.meta.client) {
            setTimeout(() => { toasts.value = toasts.value.filter(t => t.id !== id) }, ttl)
        }
    }

    return {
        toasts,
        success: (m: string) => push(m, 'success'),
        error: (m: string) => push(m, 'error'),
        info: (m: string) => push(m, 'info'),
        dismiss: (id: number) => { toasts.value = toasts.value.filter(t => t.id !== id) },
    }
}
