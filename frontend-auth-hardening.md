# Frontend Auth Hardening — Punch-List

**Audience:** Claude Code
**Repo:** `mi7plus/datamarketplace` — Nuxt 4 + Pinia frontend
**Why:** The access token lives in `localStorage` (XSS-readable → account takeover), and the refresh flow the backend already supports is unused. The backend side is ready: `/auth/refresh` (GET) reads an httpOnly `refresh_token` cookie and returns a fresh access token; CORS has `allow_credentials=True`. These fixes make the frontend actually use it.

Process: one fix = one commit = one push; verify the login → reload → call-protected-route flow by hand after each. **FE1 + FE2 are the security core**; FE3–FE5 are correctness/UX.

---

## FE1 — Move the access token out of `localStorage` (into memory)

**Problem:** `stores/auth.ts` reads/writes the access token in `localStorage`. Any XSS on any page can exfiltrate it. The token should live only in Pinia state (memory) and be re-minted from the httpOnly refresh cookie on reload.

**Steps:**
1. In `stores/auth.ts`, drop all `localStorage` access. Keep `token` in state only:
   ```ts
   setToken(token: string) { this.token = token },
   clear()    { this.token = null; this.user = null },
   logout()   { /* see FE5 */ },
   // remove init()'s localStorage read and the setItem/removeItem calls
   ```
2. Add a `refresh()` action that mints a new access token from the cookie (single-flight — see FE2):
   ```ts
   async refresh(): Promise<boolean> {
     const base = useRuntimeConfig().public.apiBase
     try {
       const res: any = await $fetch(base + '/auth/refresh', {
         method: 'GET',
         credentials: 'include',           // sends the httpOnly refresh cookie
       })
       this.setToken(res.access_token)
       return true
     } catch {
       this.clear()
       return false
     }
   }
   ```
3. Add a **client plugin** `plugins/auth.client.ts` that rehydrates on app start, so a page reload silently restores the session from the cookie:
   ```ts
   export default defineNuxtPlugin(async () => {
     const auth = useAuthStore()
     if (!auth.token) await auth.refresh()   // best-effort; failure = logged out
   })
   ```
4. Ensure `login`/`register` use `credentials: 'include'` too, so the backend can set the refresh cookie.

**Acceptance:** No `localStorage` token anywhere; after login, a full page reload keeps the user authenticated (token re-minted via cookie); clearing memory (hard reload) doesn't expose a token to JS.

---

## FE2 — Wire 401 → refresh → retry in `useApi` (single-flight)

**Problem:** `composables/useApi.ts` attaches the token but never handles expiry. When the 2-hour access token lapses, every call just throws until the user re-logs-in. The store has a `refreshing` flag but no logic behind it.

**Steps:** Rewrite the request core so a 401 triggers exactly one refresh (shared across concurrent calls), then retries:
```ts
export const useApi = () => {
  const base = useRuntimeConfig().public.apiBase
  const auth = useAuthStore()

  const authHeaders = (extra: Record<string,string> = {}) => {
    const h: Record<string,string> = { ...extra }
    if (auth.token) h['Authorization'] = `Bearer ${auth.token}`
    return h
  }

  // single-flight refresh: concurrent 401s await the same promise
  let refreshPromise: Promise<boolean> | null = null
  const refreshOnce = () => (refreshPromise ??= auth.refresh().finally(() => { refreshPromise = null }))

  const request = async (url: string, init: RequestInit, _retried = false): Promise<any> => {
    const res = await fetch(`${base}${url}`, { ...init, credentials: 'include', headers: authHeaders(init.headers as any) })
    if (res.status === 401 && !_retried) {
      if (await refreshOnce()) return request(url, init, true)   // retry once with new token
    }
    if (!res.ok) throw await toError(res, url)                   // see FE4
    return res.status === 204 ? null : res.json()
  }

  const get  = (url: string) => request(url, { method: 'GET' })
  const post = (url: string, data: any) =>
    request(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })

  return { get, post, /* postForm — see FE3 */ }
}
```

**Acceptance:** With an expired access token, a protected call transparently refreshes and succeeds; ten concurrent calls trigger exactly one `/auth/refresh`; a failed refresh logs the user out cleanly.

---

## FE3 — Multipart support in `useApi`

**Problem:** `useApi` only sends JSON (`Content-Type: application/json` + `JSON.stringify`), but submissions hit the multipart `POST /submissions/` endpoint. So the upload path hand-rolls its own `fetch` and duplicates (and can get wrong) the auth/refresh logic.

**Steps:** Add a `postForm` that reuses the same `request`/refresh core. **Do not set `Content-Type`** for `FormData` — the browser sets the multipart boundary:
```ts
const postForm = (url: string, form: FormData) =>
  request(url, { method: 'POST', body: form })   // no Content-Type header
```
Route `SubmissionForm.vue` through `useApi().postForm(...)` and delete its bespoke fetch.

**Acceptance:** File upload goes through `useApi`, inherits the 401-refresh-retry behaviour, and sends a correct multipart boundary.

---

## FE4 — Normalize FastAPI error responses

**Problem:** Error handling reads `err.detail` as a string, but FastAPI **validation** errors return `detail` as an array of objects (`[{loc, msg, type}, ...]`), which renders as `[object Object]`.

**Steps:** One helper that handles both shapes:
```ts
const toError = async (res: Response, url: string) => {
  const body = await res.json().catch(() => ({}))
  let msg = `${res.status} ${url}`
  if (typeof body.detail === 'string') msg = body.detail
  else if (Array.isArray(body.detail)) msg = body.detail.map((e: any) => e.msg).join('; ')
  return new Error(msg)
}
```

**Acceptance:** A 422 from the backend surfaces a readable field message, not `[object Object]`.

---

## FE5 — Proper logout + cookie hygiene

**Problem:** `logout()` only clears local state; the backend's refresh token (and its `refresh_token_hash`) isn't invalidated, so the httpOnly cookie remains valid until expiry.

**Steps:**
1. Add a backend `POST /auth/logout` that clears `refresh_token_hash` and deletes the cookie (`response.delete_cookie('refresh_token')`), if not already present.
2. Frontend `logout()` calls it with `credentials: 'include'`, then `clear()` and `navigateTo('/login')`.
3. Confirm CORS: `allow_credentials=True` requires `allow_origins` to be the **explicit** frontend origin (never `*`) — verify `main.py`'s `origins` is set to `FRONTEND_URL`, not a wildcard, or credentialed requests will be blocked.
4. Production note: frontend (`:3000`) and API (`:3001`) on `localhost` are same-site, so the `SameSite=Lax` refresh cookie is sent on `credentials: 'include'` calls. If you deploy them on genuinely cross-site domains, switch the cookie to `SameSite=None; Secure`.

**Acceptance:** After logout, the refresh cookie no longer mints tokens (a subsequent `/auth/refresh` returns 401); credentialed requests are accepted by CORS.

---

## Order

```
FE1  token → memory + refresh action + rehydrate plugin   ← security core
FE2  401 → single-flight refresh → retry in useApi         ← security core
FE3  multipart in useApi (route SubmissionForm through it)
FE4  normalize FastAPI error detail
FE5  real logout + CORS/cookie hygiene
```
Land FE1+FE2 together (they're interdependent), verify login→reload→expiry-refresh by hand, then FE3–FE5.

---

## Beyond auth (note, separate pass)

The transactional **states still need to be legible** in the UI: remaining capacity on a request, partial vs full acceptance, the acceptance-window countdown with the confirm/claim actions, escrow held vs released, and dispute status. Map each backend state to how it's shown and what action it offers — that's product work, tracked separately from this security list.
