import React, { useState } from 'react'
import { api, setToken } from '../api.js'
import { Field, Logo, useAct, useToast } from '../components/ui.jsx'
import { CITIES, locate } from '../views/locate.js'

const Shell = ({ children }) => (
  <>
    <header className="appbar"><Logo /></header>
    <div className="auth">{children}</div>
  </>
)

export function Login({ onAuth }) {
  const act = useAct()
  const [f, setF] = useState({ email: '', password: '' })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const submit = async (e) => {
    e.preventDefault()
    const d = await act(() => api('/auth/login', 'POST', f))
    if (d) { setToken(d.token); onAuth() }
  }
  return (
    <Shell>
      <form className="panel" onSubmit={submit}>
        <h2>Вход</h2>
        <Field label="Email" id="e"><input id="e" type="email" autoComplete="username" value={f.email} onChange={set('email')} required /></Field>
        <Field label="Пароль" id="p"><input id="p" type="password" autoComplete="current-password" value={f.password} onChange={set('password')} required /></Field>
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn" type="submit">Войти</button>
          <a className="btn alt" href="#/register">Я донор: зарегистрироваться</a>
        </div>
        <p className="muted" style={{ marginTop: 16, fontSize: 14 }}>
          Демо-доступ: station1@bpsc.kz и hospital1@bpsc.kz — Staff12345; admin@bpsc.kz — Admin12345; donor1@example.kz — Donor12345
        </p>
      </form>
    </Shell>
  )
}

export function Register({ onAuth }) {
  const act = useAct()
  const toast = useToast()
  const [f, setF] = useState({
    email: '', password: '', full_name: '', phone: '', blood_group: 'O', rh: '+',
    lat: 51.13, lon: 71.43, notify_radius_km: 10, last_donation_date: '', consent: false,
  })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const submit = async (e) => {
    e.preventDefault()
    const body = { ...f, lat: +f.lat, lon: +f.lon, notify_radius_km: +f.notify_radius_km, last_donation_date: f.last_donation_date || null }
    const d = await act(() => api('/auth/register', 'POST', body))
    if (d) { setToken(d.token); onAuth() }
  }
  const sel = (id, k, opts) => <select id={id} value={f[k]} onChange={set(k)}>{opts.map((o) => <option key={o}>{o}</option>)}</select>
  return (
    <Shell>
      <form className="panel" onSubmit={submit} style={{ maxWidth: 640 }}>
        <h2>Регистрация донора</h2>
        <p className="muted">Группу крови и контакты вы указываете один раз. Они хранятся в зашифрованном виде.</p>
        <div className="grid">
          <Field label="Email" id="e"><input id="e" type="email" value={f.email} onChange={set('email')} required /></Field>
          <Field label="Пароль (8+ символов, буквы и цифры)" id="p"><input id="p" type="password" autoComplete="new-password" value={f.password} onChange={set('password')} required /></Field>
          <Field label="ФИО" id="n"><input id="n" value={f.full_name} onChange={set('full_name')} required minLength={2} /></Field>
          <Field label="Телефон" id="ph"><input id="ph" type="tel" value={f.phone} onChange={set('phone')} required minLength={5} /></Field>
          <Field label="Группа крови" id="g">{sel('g', 'blood_group', ['O', 'A', 'B', 'AB'])}</Field>
          <Field label="Резус-фактор" id="r">{sel('r', 'rh', ['+', '-'])}</Field>
          <Field label="Последняя донация (если была)" id="ld"><input id="ld" type="date" value={f.last_donation_date} onChange={set('last_donation_date')} max={new Date().toISOString().slice(0, 10)} /></Field>
          <Field label="Радиус уведомлений, км" id="rad"><input id="rad" type="number" min="1" max="200" value={f.notify_radius_km} onChange={set('notify_radius_km')} /></Field>
          <Field label="Город (заполнить координаты)" id="city">
            <select id="city" defaultValue={CITIES[0].name} onChange={(e) => {
              const city = CITIES.find((x) => x.name === e.target.value)
              if (city) setF((x) => ({ ...x, lat: city.lat, lon: city.lon }))
            }}>{CITIES.map((city) => <option key={city.name}>{city.name}</option>)}</select>
          </Field>
          <Field label="Широта" id="la"><input id="la" type="number" step="any" value={f.lat} onChange={set('lat')} /></Field>
          <Field label="Долгота" id="lo"><input id="lo" type="number" step="any" value={f.lon} onChange={set('lon')} /></Field>
        </div>
        <button type="button" className="btn alt sm" style={{ marginTop: 10 }}
          onClick={() => locate((lat, lon) => setF((x) => ({ ...x, lat, lon })), toast)}>
          Определить меня по геолокации
        </button>
        <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', color: 'var(--ink)', marginTop: 16 }}>
          <input type="checkbox" style={{ width: 'auto', marginTop: 4 }} checked={f.consent} onChange={(e) => setF({ ...f, consent: e.target.checked })} required />
          <span>Согласен на обработку персональных данных и на получение запросов, подходящих моей группе крови</span>
        </label>
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn" type="submit">Зарегистрироваться</button>
          <a className="btn alt" href="#/login">Уже есть аккаунт</a>
        </div>
      </form>
    </Shell>
  )
}
