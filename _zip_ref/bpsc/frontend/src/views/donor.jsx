import React, { useMemo, useState } from 'react'
import { api } from '../api.js'
import { Dialog, Field, Loading, Panel, Table, Tag, useAct, useLoad, useToast } from '../components/ui.jsx'
import { COMPONENTS, addDays, dayNum, fmtDate, fmtDateTime, fmtDay, grp, isSunday, plural, t, todayYmd, weekday } from '../labels.js'
import { CITIES, locate } from './locate.js'

const DONATION_STATUS = {
  testing: 'Ожидает тестирования', tested: 'Протестирована',
  stored: 'Хранится на станции', reserved: 'Зарезервирована для пациента',
  transfused: 'Использована при переливании', discarded: 'Списана',
}

function NextVisit({ a, onCancel }) {
  return (
    <div className="banner">
      <div>
        <strong>Вы записаны на {fmtDateTime(a.slot_at)}</strong>
        <span className="muted">{a.station}, {t(a.component).toLowerCase()}{a.request_id ? `, по запросу №${a.request_id}` : ''}</span>
      </div>
      <button className="btn alt sm" onClick={onCancel}>Отменить запись</button>
    </div>
  )
}

export function DonorHome({ goTo }) {
  const act = useAct()
  const { data: ov, reload } = useLoad(() => api('/donors/me/overview'))
  const { data: notes } = useLoad(() => api('/notifications/my'))
  const [confirm, setConfirm] = useState(false)
  if (!ov || !notes) return <Loading />
  const waiting = notes.filter((n) => n.status === 'sent').length
  const next = ov.next_appointment
  const cancel = () => act(() => api(`/appointments/${next.id}/cancel`, 'POST'), 'Запись отменена').then(() => { setConfirm(false); reload() })
  return (
    <>
      {next ? <NextVisit a={next} onCancel={() => setConfirm(true)} /> : (
        <div className="banner calm">
          <div><strong>Вы пока не записаны на визит</strong><span className="muted">Выберите станцию и удобное время за пару шагов.</span></div>
          <button className="btn" onClick={() => goTo('book')}>Записаться</button>
        </div>
      )}
      {waiting > 0 && (
        <div className="banner">
          <div><strong>{waiting} {plural(waiting, ['запрос ждёт', 'запроса ждут', 'запросов ждут'])} вашего ответа</strong><span className="muted">Они подобраны по вашей группе крови и расстоянию.</span></div>
          <button className="btn" onClick={() => goTo('requests')}>Посмотреть запросы</button>
        </div>
      )}
      <Panel title="Когда можно сдавать снова">
        <Table rows={ov.eligibility.map((e) => ({ ...e, id: e.component }))} cols={[
          ['Компонент', (e) => t(e.component)],
          ['Статус', (e) => e.eligible_now ? <span className="good">можно сейчас</span>
            : <span className="warn">с {fmtDay(e.next_date)}, через {e.days_left} {plural(e.days_left, ['день', 'дня', 'дней'])}</span>],
          ['Интервал между донациями', (e) => `${e.interval_days} дн.`]]} />
      </Panel>
      <Panel title="Ваши донации">
        <dl className="facts">
          <div><dt>Всего донаций</dt><dd>{ov.stats.donations}</dd></div>
          <div><dt>Сдано, мл</dt><dd>{ov.stats.volume_ml}</dd></div>
          <div><dt>Использовано при переливании</dt><dd>{ov.stats.transfused}</dd></div>
        </dl>
      </Panel>
      {confirm && (
        <Dialog title="Отменить запись?" onClose={() => setConfirm(false)}>
          <p className="muted">Время освободится для других доноров. Вы сможете записаться снова.</p>
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn" onClick={cancel}>Отменить запись</button>
            <button className="btn alt" onClick={() => setConfirm(false)}>Оставить</button>
          </div>
        </Dialog>
      )}
    </>
  )
}

export function DonorRequests({ goTo }) {
  const act = useAct()
  const { data: notes, reload } = useLoad(() => api('/notifications/my'))
  if (!notes) return <Loading />
  const decline = (n) => act(() => api(`/notifications/${n.id}/respond`, 'POST', { accept: false }), 'Ответ отправлен').then(reload)
  return (
    <Panel title="Запросы на донацию">
      <Table rows={notes} empty="Запросов пока нет. Когда больнице понадобится ваша группа крови, запрос появится здесь." cols={[
        ['Больница', (n) => n.hospital], ['Нужно', (n) => `${t(n.component)} ${grp(n)}`], ['Срочность', (n) => t(n.urgency)],
        ['Статус', (n) => <Tag kind={n.status === 'sent' ? 'warn' : n.status === 'accepted' ? 'good' : ''}>{t(n.status)}</Tag>],
        ['', (n) => (n.status === 'sent' || n.status === 'accepted') && (
          <>
            <button className="btn sm" onClick={() => goTo('book', { request: n })}>{n.status === 'sent' ? 'Могу прийти' : 'Выбрать время'}</button>
            {n.status === 'sent' && <button className="btn sm alt" onClick={() => decline(n)}>Не смогу</button>}
          </>)]]} />
    </Panel>
  )
}

export function DonorBooking({ goTo, ctx }) {
  const act = useAct()
  const req = ctx?.request || null
  const ov = useLoad(() => api('/donors/me/overview'))
  const stations = useLoad(() => api('/stations'))
  const mine = useLoad(() => api('/appointments/my'))
  const [sid, setSid] = useState('')
  const [comp, setComp] = useState(req?.component || 'whole_blood')
  const [sel, setSel] = useState(null)
  const [pick, setPick] = useState({ key: '', iso: null })

  const today = todayYmd()
  const elig = ov.data?.eligibility.find((e) => e.component === comp)
  const ok = (d) => !isSunday(d) && (!elig || d >= elig.next_date)
  const days = useMemo(() => Array.from({ length: 31 }, (_, i) => addDays(today, i)), [today])
  const day = sel && ok(sel) ? sel : days.find(ok) || null
  const stationId = sid || stations.data?.[0]?.id || ''
  const slots = useLoad(() => (day && stationId ? api(`/stations/${stationId}/slots?day=${day}`) : Promise.resolve([])), [stationId, day])
  if (!ov.data || !stations.data || !mine.data) return <Loading />

  const key = `${stationId}|${day}`
  const chosen = pick.key === key ? pick.iso : null
  const next = ov.data.next_appointment
  const cancel = (id) => act(() => api(`/appointments/${id}/cancel`, 'POST'), 'Запись отменена').then(() => { ov.reload(); mine.reload() })
  const submit = async (e) => {
    e.preventDefault()
    const r = await act(() => api('/appointments', 'POST', { station_id: +stationId, slot_at: chosen, component: comp, request_id: req?.request_id ?? null }), 'Вы записаны на визит')
    if (r) goTo('home')
  }

  return (
    <>
      {next ? (
        <>
          <NextVisit a={next} onCancel={() => cancel(next.id)} />
          <p className="muted" style={{ marginBottom: 16 }}>Чтобы выбрать другое время, сначала отмените текущую запись.</p>
        </>
      ) : (
        <Panel title="Запись на визит">
          {req && <p className="banner calm" style={{ display: 'block' }}><strong>Запрос от {req.hospital}</strong>Нужно: {t(req.component).toLowerCase()} {grp(req)}, срочность: {t(req.urgency).toLowerCase()}.</p>}
          <form onSubmit={submit}>
            <div className="grid">
              <Field label="Станция" id="st">
                <select id="st" value={stationId} onChange={(e) => setSid(e.target.value)}>
                  {stations.data.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </Field>
              <Field label="Что сдаёте" id="cp">
                <select id="cp" value={comp} onChange={(e) => setComp(e.target.value)} disabled={!!req}>
                  {COMPONENTS.map((c) => <option key={c} value={c}>{t(c)}</option>)}
                </select>
              </Field>
            </div>
            {elig && !elig.eligible_now && <p className="warn" style={{ marginTop: 10 }}>Этот компонент можно сдавать с {fmtDay(elig.next_date)}. Раньше записаться нельзя.</p>}
            <h3>Дата</h3>
            {day ? (
              <div className="days" role="group" aria-label="Дата визита">
                {days.map((d) => (
                  <button type="button" key={d} className={`day ${d === day ? 'on' : ''}`} disabled={!ok(d)} onClick={() => setSel(d)} aria-pressed={d === day}>
                    <small>{weekday(d)}</small><b>{dayNum(d)}</b>
                  </button>
                ))}
              </div>
            ) : <p className="warn">В ближайшие 30 дней записаться на этот компонент нельзя: интервал между донациями ещё не прошёл.</p>}
            {day && (
              <>
                <h3>Время, {fmtDay(day)}</h3>
                {slots.loading ? <Loading /> : slots.data?.length ? (
                  <div className="slots" role="group" aria-label="Время визита">
                    {slots.data.map((s) => (
                      <button type="button" key={s.slot_at} className={`slot ${s.slot_at === chosen ? 'on' : ''}`} disabled={!s.free}
                        onClick={() => setPick({ key, iso: s.slot_at })} aria-pressed={s.slot_at === chosen}>
                        {s.time}<small>{s.free ? `свободно: ${s.free}` : 'занято'}</small>
                      </button>
                    ))}
                  </div>
                ) : <p className="empty">На этот день свободного времени нет. Выберите другую дату.</p>}
              </>
            )}
            <button className="btn" type="submit" disabled={!chosen} style={{ marginTop: 16 }}>Записаться</button>
          </form>
        </Panel>
      )}
      <Panel title="Мои визиты">
        <Table rows={mine.data} empty="Вы ещё не записывались." cols={[
          ['Когда', (a) => fmtDateTime(a.slot_at)], ['Станция', (a) => a.station], ['Компонент', (a) => t(a.component)],
          ['Статус', (a) => <Tag kind={a.status === 'completed' ? 'good' : a.status === 'booked' ? 'warn' : ''}>{t(a.status)}</Tag>]]} />
      </Panel>
    </>
  )
}

export function DonorHistory({ goTo }) {
  const { data: ov } = useLoad(() => api('/donors/me/overview'))
  if (!ov) return <Loading />
  return (
    <Panel title="История донаций">
      {ov.history.length ? (
        <>
          <Table rows={ov.history} cols={[
            ['Дата', (u) => fmtDate(u.collected_at)], ['Станция', (u) => u.station], ['Компонент', (u) => t(u.component)],
            ['Объём, мл', (u) => u.volume_ml], ['Что с ней сейчас', (u) => DONATION_STATUS[u.status] || t(u.status)]]} />
          <p className="muted" style={{ marginTop: 10 }}>Спасибо! Здесь видно только судьбу вашей донации, без данных о пациентах.</p>
        </>
      ) : (
        <div className="empty">
          <p>Здесь появятся ваши донации после первого визита на станцию.</p>
          <button className="btn" style={{ marginTop: 12 }} onClick={() => goTo('book')}>Записаться на визит</button>
        </div>
      )}
    </Panel>
  )
}

export function DonorProfile() {
  const act = useAct()
  const toast = useToast()
  const { data: d } = useLoad(() => api('/donors/me'))
  const [f, setF] = useState(null)
  if (!d) return <Loading />
  const v = f || { notify_radius_km: d.notify_radius_km, lat: d.lat, lon: d.lon, consent: d.consent }
  const set = (k) => (e) => setF({ ...v, [k]: e.target.value })
  const save = (e) => {
    e.preventDefault()
    act(() => api('/donors/me', 'PUT', { notify_radius_km: +v.notify_radius_km, lat: +v.lat, lon: +v.lon, consent: v.consent === true || v.consent === 'true' }), 'Профиль сохранён')
  }
  return (
    <Panel title="Мой профиль">
      <p>{d.full_name}, группа крови {grp(d)}. Последняя донация: {d.last_donation_date ? fmtDate(d.last_donation_date) : 'нет'}.</p>
      <form onSubmit={save}>
        <div className="grid">
          <Field label="Радиус уведомлений, км" id="rad"><input id="rad" type="number" min="1" max="200" value={v.notify_radius_km} onChange={set('notify_radius_km')} /></Field>
          <Field label="Город (заполнить координаты)" id="city">
            <select id="city" defaultValue="" onChange={(e) => {
              const city = CITIES.find((x) => x.name === e.target.value)
              if (city) setF({ ...v, lat: city.lat, lon: city.lon })
            }}>
              <option value="">Выберите город</option>
              {CITIES.map((city) => <option key={city.name}>{city.name}</option>)}
            </select>
          </Field>
          <Field label="Широта" id="la"><input id="la" type="number" step="any" value={v.lat} onChange={set('lat')} /></Field>
          <Field label="Долгота" id="lo"><input id="lo" type="number" step="any" value={v.lon} onChange={set('lon')} /></Field>
          <Field label="Получать запросы и участвовать в подборе" id="co">
            <select id="co" value={String(v.consent)} onChange={(e) => setF({ ...v, consent: e.target.value === 'true' })}>
              <option value="true">Да</option><option value="false">Нет</option>
            </select>
          </Field>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn" type="submit">Сохранить</button>
          <button className="btn alt" type="button" onClick={() => locate((lat, lon) => setF({ ...v, lat, lon }), toast)}>Определить меня по геолокации</button>
        </div>
      </form>
    </Panel>
  )
}
