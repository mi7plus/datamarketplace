import { useAuthStore } from '~/stores/auth'

export const useApi = () => {
    const config = useRuntimeConfig()
    const base = config.public.apiBase
    const auth = useAuthStore()

    const buildHeaders = () => {
        const headers: Record<string, string> = {
            'Content-Type': 'application/json'
        }

        if (auth.token) {
            headers['Authorization'] = `Bearer ${auth.token}`
        }

        return headers
    }

    const get = async (url: string) => {
        const res = await fetch(`${base}${url}`, {
            method: 'GET',
            headers: buildHeaders()
        })

        if (!res.ok) {
            const err = await res.json().catch(() => ({}))
            throw new Error(err.detail || `GET ${url} failed`)
        }

        return res.json()
    }

    const post = async (url: string, data: any) => {
        const res = await fetch(`${base}${url}`, {
            method: 'POST',
            headers: buildHeaders(),
            body: JSON.stringify(data)
        })

        if (!res.ok) {
            const err = await res.json().catch(() => ({}))
            throw new Error(err.detail || `POST ${url} failed`)
        }

        return res.json()
    }

    return { get, post }
}