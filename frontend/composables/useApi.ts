import { useAuthStore } from '~/stores/auth'

export const useApi = () => {
    const base = useRuntimeConfig().public.apiBase
    const auth = useAuthStore()

    const authHeaders = (extra: Record<string, string> = {}) => {
        const h: Record<string, string> = { ...extra }
        if (auth.token) h['Authorization'] = `Bearer ${auth.token}`
        return h
    }

    // Normalize FastAPI error bodies into a readable Error. FastAPI returns
    // `detail` as a string for HTTPException, but as an array of {loc,msg,type}
    // objects for request-validation (422) errors — which would otherwise render
    // as "[object Object]". Handle both shapes.
    const toError = async (res: Response, url: string) => {
        const body: any = await res.json().catch(() => ({}))
        let msg = `${res.status} ${url}`
        if (typeof body.detail === 'string') {
            msg = body.detail
        } else if (Array.isArray(body.detail)) {
            msg = body.detail.map((e: any) => e.msg).filter(Boolean).join('; ') || msg
        }
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

    // Multipart upload — reuses the same auth + 401-refresh-retry core.
    // Deliberately set NO Content-Type: the browser sets the multipart boundary.
    const postForm = (url: string, form: FormData) =>
        request(url, { method: 'POST', body: form })

    return { get, post, postForm }
}
