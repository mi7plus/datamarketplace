// composables/useApi.ts
import { useAuthStore } from '~/stores/auth'

export const useApi = () => {
    const config = useRuntimeConfig()
    const base = config.public.apiBase
    const auth = useAuthStore()

    const get = async (url: string) => {
        const headers: any = { 'Content-Type': 'application/json' }
        if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`

        const res = await fetch(`${base}${url}`, { headers })
        if (!res.ok) throw new Error(`GET ${url} failed: ${res.status}`)
        return res.json()
    }

    const post = async (url: string, data: any) => {
        const headers: any = { 'Content-Type': 'application/json' }
        if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`

        const res = await fetch(`${base}${url}`, {
            method: 'POST',
            headers,
            body: JSON.stringify(data)
        })
        if (!res.ok) throw new Error(`POST ${url} failed: ${res.status}`)
        return res.json()
    }

    const put = async (url: string, data: any) => {
        const headers: any = { 'Content-Type': 'application/json' }
        if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`

        const res = await fetch(`${base}${url}`, {
            method: 'PUT',
            headers,
            body: JSON.stringify(data)
        })
        if (!res.ok) throw new Error(`PUT ${url} failed: ${res.status}`)
        return res.json()
    }

    const del = async (url: string) => {
        const headers: any = {}
        if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`

        const res = await fetch(`${base}${url}`, {
            method: 'DELETE',
            headers
        })
        if (!res.ok) throw new Error(`DELETE ${url} failed: ${res.status}`)
        return res.json()
    }

    return { get, post, put, del }
}