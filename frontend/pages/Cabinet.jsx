import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Logo, useLoad, useToast } from '../components/ui.jsx'
import { t } from '../labels.js'
import { DonorHome, DonorRequests, DonorBooking, DonorHistory, DonorProfile } from '../views/donor.jsx'
import { Inventory, MapView, Requests, Trace, Report } from '../views/shared.jsx'
import { Donate, Visits, Rebalance } from '../views/station.jsx'
import { NewRequest, Forecast } from '../views/hospital.jsx'
import { Users, Audit } from '../views/admin.jsx'

// Вкладки по ролям: [ключ, название, компонент]
const TABS = {
  donor: [['home', 'Обзор', DonorHome], ['requests', 'Запросы', DonorRequests], ['map', 'Карта', MapView], ['book', 'Запись на визит', DonorBooking],
          ['history', 'История донаций', DonorHistory], ['profile', 'Профиль', DonorProfile]],
  station: [['inv', 'Запасы', Inventory], ['visits', 'Записи доноров', Visits], ['donate', 'Принять донацию', Donate],
            ['reqs', 'Заявки', Requests], ['rebal', 'Перераспределение', Rebalance], ['trace', 'Трассировка', Trace], ['report', 'Отчёт', Report]],
  hospital: [['new', 'Новая заявка', NewRequest], ['reqs', 'Мои заявки', Requests], ['inv', 'Запасы региона', Inventory],
             ['forecast', 'Прогноз', Forecast], ['trace', 'Трассировка', Trace]],
  admin: [['users', 'Пользователи', Users], ['audit', 'Аудит', Audit], ['report', 'Отчёт', Report], ['inv', 'Запасы', Inventory]],
}

export default function Cabinet({ me, logout }) {
  const toast = useToast()
  const tabs = TABS[me.role]
  const [tab, setTab] = useState(tabs[0][0])
  const [ctx, setCtx] = useState(null) // данные, передаваемые между вкладками (например, запрос для записи)
  const [version, setVersion] = useState(0) // меняется — вкладка загружается заново
  const [liveNotes, setLiveNotes] = useState(null)
  const previousSent = useRef(null)
  const goTo = useCallback((key, data = null) => { setCtx(data); setTab(key); setVersion((v) => v + 1) }, [])
  const inst = useLoad(() => (me.role === 'donor' ? Promise.resolve([]) : api('/institutions')), [me.role])
  const pending = useLoad(() => (me.role === 'donor' ? api('/notifications/my') : Promise.resolve([])), [version, me.role])
  const donorNotes = liveNotes ?? pending.data
  const waiting = (donorNotes || []).filter((n) => n.status === 'sent').length

  const refreshNotes = useCallback(async () => {
    const notes = await api('/notifications/my')
    const sent = notes.filter((n) => n.status === 'sent')
    const ids = new Set(sent.map((n) => n.id))
    if (previousSent.current && [...ids].some((id) => !previousSent.current.has(id))) {
      toast('Появился новый запрос на донацию')
    }
    previousSent.current = ids
    setLiveNotes(notes)
    return notes
  }, [toast])

  useEffect(() => { document.title = 'Кабинет — BPSC' }, [])
  useEffect(() => {
    if (me.role !== 'donor') return
    let active = true
    let failed = false
    const refresh = async () => {
      try {
        if (!active) return
        await refreshNotes()
        failed = false
      } catch (error) {
        if (active && !failed) toast(`Не удалось обновить уведомления: ${error.message}`, true)
        failed = true
      }
    }
    refresh()
    const timer = setInterval(refresh, 10000)
    return () => { active = false; clearInterval(timer) }
  }, [me.role, toast, refreshNotes])
  const View = tabs.find((x) => x[0] === tab)[2]

  return (
    <>
      <header className="appbar">
        <Logo />
        <span className="who muted">{me.email}, {t(me.role)}{me.institution ? `, ${me.institution.name}` : ''}</span>
        {me.role === 'donor' && <button className="btn alt sm" onClick={() => goTo('requests')} aria-label={`Уведомления: ${waiting} ожидают ответа`}>
          Уведомления{waiting > 0 && <span className="dot" style={{ marginLeft: 6 }}>{waiting}</span>}
        </button>}
        <button className="btn alt sm" onClick={logout}>Выйти</button>
      </header>
      <main className="app">
        <nav className="tabs" aria-label="Разделы">
          {tabs.map(([k, name]) => (
            <button key={k} className={k === tab ? 'on' : ''} aria-current={k === tab ? 'page' : undefined} onClick={() => goTo(k)}>
              {name}{k === 'requests' && waiting > 0 && <span className="dot" aria-label={`ждут ответа: ${waiting}`}>{waiting}</span>}
            </button>
          ))}
        </nav>
        <View key={tab + version} me={me} institutions={inst.data || []} goTo={goTo} ctx={ctx}
          notifications={me.role === 'donor' ? donorNotes : undefined} reloadNotifications={me.role === 'donor' ? refreshNotes : undefined} />
      </main>
    </>
  )
}
