import { useAuthStore } from '~/stores/auth'

export const useApi = () => {
    const base = useRuntimeConfig().public.apiBase
    const auth = useAuthStore()

    const authHeaders = (extra: Record<string, string> = {}) => {
        const h: Record<string, string> = { ...extra }
        if (auth.token) h['Authorization'] = `Bearer ${auth.token}`
        return h
    }

    // Normalize FastAPI error bodies into a readable Error.
    // FE4 extends this to handle validation errors (detail as an array of objects).
    const toError = async (res: Response, url: string) => {
        const body: any = await res.json().catch(() => ({}))
        let msg = `${res.status} ${url}`
        if (typeof body.detail === 'string') msg = body.detail
        return new Error(msg)
    }

    // Single-flight refresh: concurrent 401s await the same refresh promise, so a
    // burst of expired-token calls triggers exactly one /auth/refresh.
    let refreshPromise: Promise<boolean> | null = null
    const refreshOnce = () =>
        (refreshPromise ??= auth.refresh().finally(() => { refreshPromise = null }))

    const request = async (url: string, init: RequestInit, _retried = false): Promise<any> => {
        const res = await fetch(`${base}${url}`, {
            ...init,
            credentials: 'include',
            headers: authHeaders(init.headers as Record<string, string>),
        })

        if (res.status === 401 && !_retried) {
            // Token likely expired — refresh once (shared) and retry the call.
            if (await refreshOnce()) return request(url, init, true)
        }

        if (!res.ok) throw await toError(res, url)
        return res.status === 204 ? null : res.json()
    }

    const get = (url: string) => request(url, { method: 'GET' })

    const post = (url: string, data: any) =>
        request(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        })

    return { get, post }
}
