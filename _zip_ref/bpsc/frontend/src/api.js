// Тонкая обёртка над fetch: подставляет токен и превращает ошибки API в Error с понятным текстом.
let token = null
try { token = sessionStorage.getItem('t') } catch { /* sessionStorage недоступен */ }

export const getToken = () => token
export function setToken(t) {
  token = t
  try { t ? sessionStorage.setItem('t', t) : sessionStorage.clear() } catch { /* ignore */ }
}

export async function api(path, method = 'GET', body) {
  const r = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  const d = await r.json().catch(() => ({}))
  if (!r.ok) {
    const m = Array.isArray(d.detail) ? d.detail.map((x) => x.msg).join('; ') : d.detail || 'Ошибка'
    const e = new Error(m)
    e.status = r.status
    throw e
  }
  return d
}
