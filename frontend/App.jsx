import React, { useCallback, useEffect, useState } from 'react'
import { api, getToken, setToken } from './api.js'
import { ToastProvider } from './components/ui.jsx'
import Landing from './pages/Landing.jsx'
import { Login, Register } from './pages/Auth.jsx'
import Cabinet from './pages/Cabinet.jsx'

const useHash = () => {
  const [h, setH] = useState(window.location.hash || '#/')
  useEffect(() => {
    const on = () => { setH(window.location.hash || '#/'); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return h
}
export const go = (path) => { window.location.hash = path }

export default function App() {
  const hash = useHash()
  const [me, setMe] = useState(null)
  const [ready, setReady] = useState(!getToken())

  const loadMe = useCallback(async () => {
    try { setMe(await api('/me')) } catch { setToken(null); setMe(null) }
    setReady(true)
  }, [])
  useEffect(() => { if (getToken()) loadMe() }, [loadMe])

  const logout = () => { setToken(null); setMe(null); go('#/') }
  const onAuth = async () => { await loadMe(); go('#/app') }

  if (!ready) return null
  let page
  if (hash.startsWith('#/app')) page = me ? <Cabinet me={me} logout={logout} /> : <Login onAuth={onAuth} />
  else if (hash === '#/login') page = me ? <Cabinet me={me} logout={logout} /> : <Login onAuth={onAuth} />
  else if (hash === '#/register') page = <Register onAuth={onAuth} />
  else page = <Landing me={me} />
  return <ToastProvider>{page}</ToastProvider>
}
