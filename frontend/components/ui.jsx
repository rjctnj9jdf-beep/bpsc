import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }) {
  const [msg, setMsg] = useState(null)
  const timer = useRef()
  const toast = useCallback((text, bad) => {
    setMsg({ text, bad })
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setMsg(null), 4000)
  }, [])
  return (
    <ToastCtx.Provider value={toast}>
      {children}
      {msg && <div id="toast" role="status" className={msg.bad ? 'bad' : ''}>{msg.text}</div>}
    </ToastCtx.Provider>
  )
}

/** Загружает данные при монтировании; reload() обновляет. Ошибки показываются тостом. */
export function useLoad(fn, deps = []) {
  const toast = useToast()
  const [state, setState] = useState({ data: null, loading: true })
  const run = useCallback(async () => {
    try {
      setState({ data: await fn(), loading: false })
    } catch (e) {
      toast(e.message, true)
      setState({ data: null, loading: false, error: e })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { run() }, [run])
  return { ...state, reload: run }
}

/** Выполняет действие, показывает ошибку или сообщение об успехе. Возвращает результат или undefined. */
export function useAct() {
  const toast = useToast()
  return useCallback(async (fn, ok) => {
    try {
      const r = await fn()
      if (ok) toast(typeof ok === 'function' ? ok(r) : ok)
      return r ?? true
    } catch (e) {
      toast(e.message, true)
    }
  }, [toast])
}

export const Panel = ({ title, children }) => (
  <section className="panel">{title && <h2>{title}</h2>}{children}</section>
)

export function Table({ cols, rows, empty = 'Пока нет данных.' }) {
  if (!rows || !rows.length) return <p className="empty">{empty}</p>
  return (
    <div className="scroll">
      <table>
        <thead><tr>{cols.map((c) => <th key={c[0]}>{c[0]}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={r.id ?? r.donor_id ?? i}>{cols.map((c) => <td key={c[0]}>{c[1](r)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

export function BarChart({ items, label = 'График' }) {
  const max = Math.max(1, ...items.map((item) => item.value))
  return (
    <div className="bar-chart" role="img" aria-label={label}>
      {items.map((item) => (
        <div className="bar-row" key={item.label}>
          <span>{item.label}</span>
          <div className="bar-track"><i style={{ width: `${Math.max(item.value ? 3 : 0, item.value / max * 100)}%` }} /></div>
          <b>{item.value}</b>
        </div>
      ))}
    </div>
  )
}

export const Field = ({ label, id, children }) => (
  <div><label htmlFor={id}>{label}</label>{children}</div>
)

export const Loading = () => <p className="empty" aria-live="polite">Загрузка…</p>

export const Tag = ({ kind = '', children }) => <span className={`tag ${kind}`}>{children}</span>

export function Logo({ href = '#/' }) {
  return (
    <a className="logo" href={href} aria-label="BPSC, на главную">
      <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 3C16 3 6 14 6 20a10 10 0 0 0 20 0C26 14 16 3 16 3z" /></svg>
      BPSC
    </a>
  )
}

/** Модальное окно на нативном <dialog>: Esc и фокус работают из коробки. */
export function Dialog({ title, onClose, children }) {
  const ref = useRef()
  useEffect(() => {
    const d = ref.current
    if (d && !d.open) d.showModal()
    return () => { if (d && d.open) d.close() }
  }, [])
  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => e.target === ref.current && onClose()}>
      <h2>{title}</h2>
      {children}
    </dialog>
  )
}
