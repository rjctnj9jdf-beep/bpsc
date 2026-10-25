import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { BarChart, Dialog, Loading, Panel, Table, useAct, useLoad } from '../components/ui.jsx'
import { grp, hoursLabel, t } from '../labels.js'

const esc = (x) => x ?? ''

export function Inventory({ me, institutions }) {
  const act = useAct()
  const { data: d, reload } = useLoad(() => api('/inventory'))
  const [move, setMove] = useState(null)
  const [to, setTo] = useState('')
  if (!d) return <Loading />
  const active = (u) => u.status === 'stored' || u.status === 'reserved'
  const event = (id, body, ok) => act(() => api(`/units/${id}/events`, 'POST', body), ok).then((r) => r && reload())
  const test = (id, passed) => act(() => api(`/units/${id}/test`, 'POST', { passed }),
    passed ? 'Тест пройден' : 'Единица списана: тест не пройден').then((r) => r && reload())
  const store = (id) => act(() => api(`/units/${id}/store`, 'POST'), 'Единица помещена на хранение').then((r) => r && reload())
  const stockByGroup = Object.values(d.region_stock.reduce((acc, row) => {
    const key = `${row.blood_group}${row.rh}`
    acc[key] = acc[key] || { label: key, value: 0 }
    acc[key].value += row.c
    return acc
  }, {})).sort((a, b) => a.label.localeCompare(b.label))
  const expiryItems = [
    { label: 'Просрочено', value: d.units.filter((u) => u.expired).length },
    { label: 'Истекает за 72 ч', value: d.units.filter((u) => u.expiring).length },
    { label: 'Срок в норме', value: d.units.filter((u) => !u.expiring && !u.expired).length },
  ]
  const cols = [
    ['№', (u) => u.id], ['Компонент', (u) => t(u.component)], ['Группа', grp], ['Объём, мл', (u) => u.volume_ml],
    ['Срок', (u) => { const h = hoursLabel(u); return <span className={h.cls}>{h.text}</span> }],
    ['Статус', (u) => t(u.status)],
    ['', (u) => me.role === 'admin' ? '' : (
      <>
        {me.role === 'station' && active(u) && <button className="btn sm alt" onClick={() => { setMove(u); setTo(String(institutions.find((i) => i.id !== me.institution.id)?.id ?? '')) }}>Передать</button>}
        {me.role === 'station' && u.status === 'testing' && <>
          <button className="btn sm" disabled={u.expired} onClick={() => test(u.id, true)}>Тест пройден</button>
          <button className="btn sm alt" onClick={() => test(u.id, false)}>Тест не пройден</button>
        </>}
        {me.role === 'station' && u.status === 'tested' && <button className="btn sm" disabled={u.expired} onClick={() => store(u.id)}>На хранение</button>}
        {me.role === 'hospital' && active(u) && u.institution_id === me.institution.id &&
          <button className="btn sm alt" onClick={() => event(u.id, { event_type: 'transfused' }, 'Переливание записано')}>Переливание</button>}
        {active(u) && u.institution_id === me.institution?.id &&
          <button className="btn sm alt" onClick={() => event(u.id, { event_type: 'discarded', note: 'списание вручную' }, 'Единица списана')}>Списать</button>}
      </>
    )],
  ]
  return (
    <>
      <Panel title={`Дефицит по региону (меньше ${d.threshold} ед.)`}>
        {d.deficits.length
          ? d.deficits.map((x) => <span key={x.component + grp(x)} className="tag bad" style={{ marginRight: 6 }} title={`${x.count} ед.`}>{t(x.component)} {grp(x)}: {x.count}</span>)
          : <span className="good">Дефицита нет</span>}
      </Panel>
      <Panel title="Запасы по группам крови">
        {stockByGroup.length
          ? <BarChart items={stockByGroup} label="Количество единиц запаса по группам крови" />
          : <p className="empty">Нет единиц на хранении.</p>}
        <h3>Сроки годности на вашем складе</h3>
        <BarChart items={expiryItems} label="Единицы по срокам годности" />
      </Panel>
      <Panel title={me.role === 'admin' ? 'Все единицы' : 'Единицы учреждения'}>
        <Table cols={cols} rows={d.units} />
        <button className="btn" style={{ marginTop: 12 }} onClick={() => act(() => api('/maintenance/expire', 'POST'), (r) => `Списано: ${r.discarded}`).then(reload)}>Списать просроченные</button>
      </Panel>
      {move && (
        <Dialog title={`Передать единицу №${move.id}`} onClose={() => setMove(null)}>
          <label htmlFor="to">Учреждение назначения</label>
          <select id="to" value={to} onChange={(e) => setTo(e.target.value)}>
            {institutions.filter((i) => i.id !== me.institution.id).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn" disabled={!to} onClick={() => event(move.id, { event_type: 'transferred', to_institution_id: +to }, 'Единица передана').then(() => setMove(null))}>Передать</button>
            <button className="btn alt" onClick={() => setMove(null)}>Отмена</button>
          </div>
        </Dialog>
      )}
    </>
  )
}

export function Requests({ me }) {
  const act = useAct()
  const { data: rows, reload } = useLoad(() => api('/requests'))
  const [donors, setDonors] = useState(null)
  const [closing, setClosing] = useState(null)
  useEffect(() => {
    const timer = setInterval(reload, 15000)
    return () => clearInterval(timer)
  }, [reload])
  if (!rows) return <Loading />
  const open = (r) => !['fulfilled', 'cancelled'].includes(r.status)
  const cols = [
    ['№', (r) => r.id], ['Больница', (r) => esc(r.hospital)], ['Компонент', (r) => t(r.component)], ['Группа', grp],
    ['Нужно', (r) => r.units_needed], ['В резерве', (r) => r.reserved_units], ['Срочность', (r) => t(r.urgency)], ['Статус', (r) => t(r.status)],
    ['', (r) => open(r) && (
      <>
        <button className="btn sm alt" onClick={async () => { const m = await act(() => api(`/requests/${r.id}/donors`)); if (m) setDonors({ id: r.id, list: m }) }}>Доноры</button>
        <button className="btn sm alt" onClick={() => act(() => api(`/requests/${r.id}/notify`, 'POST'), (x) => `Новых уведомлений: ${x.new_notifications}`)}>Оповестить</button>
        <button className="btn sm alt" onClick={() => act(() => api(`/requests/${r.id}/reserve`, 'POST'), (x) => `Зарезервировано: ${x.reserved_now}`).then(reload)}>Резерв</button>
        {me.role === 'hospital' && <button className="btn sm alt" onClick={() => setClosing(r)}>Закрыть</button>}
      </>
    )],
  ]
  return (
    <>
      <Panel title="Заявки на кровь"><Table cols={cols} rows={rows} /></Panel>
      {donors && (
        <Panel title={`Подходящие доноры по заявке №${donors.id} (обезличено): ${donors.list.length}`}>
          <Table rows={donors.list.slice(0, 30)} empty="Подходящих доноров нет." cols={[
            ['Донор', (x) => '#' + x.donor_id], ['Группа', grp], ['Расстояние, км', (x) => x.distance_km], ['Дней с донации', (x) => x.days_since_last_donation ?? '—']]} />
        </Panel>
      )}
      {closing && (
        <Dialog title={`Закрыть заявку №${closing.id}`} onClose={() => setClosing(null)}>
          <p className="muted">Выберите итог. Закрытую заявку изменить нельзя.</p>
          <div className="row" style={{ marginTop: 16 }}>
            {[['fulfilled', 'Выполнена'], ['cancelled', 'Отменить заявку']].map(([s, name]) =>
              <button key={s} className={s === 'fulfilled' ? 'btn' : 'btn alt'} onClick={() => act(() => api(`/requests/${closing.id}/close`, 'POST', { status: s }), 'Заявка закрыта').then(() => { setClosing(null); reload() })}>{name}</button>)}
            <button className="btn alt" onClick={() => setClosing(null)}>Назад</button>
          </div>
        </Dialog>
      )}
    </>
  )
}

const EVENTS = { collected: 'Сдача', tested: 'Тестирование', stored: 'Хранение', reserved: 'Резерв', transferred: 'Передача', transfused: 'Переливание', discarded: 'Списание' }

export function Trace({ institutions }) {
  const act = useAct()
  const [id, setId] = useState('')
  const [d, setD] = useState(null)
  const names = Object.fromEntries(institutions.map((i) => [i.id, i.name]))
  const show = async (e) => { e.preventDefault(); const r = await act(() => api(`/units/${id}/trace`)); if (r) setD(r) }
  return (
    <Panel title="Путь единицы крови">
      <form onSubmit={show}>
        <label htmlFor="u">Номер единицы</label>
        <input id="u" type="number" min="1" value={id} onChange={(e) => setId(e.target.value)} required />
        <div><button className="btn" type="submit" style={{ marginTop: 10 }}>Показать</button></div>
      </form>
      {d && (
        <>
          <p style={{ marginTop: 14 }}>{t(d.unit.component)} {grp(d.unit)}, {t(d.unit.status).toLowerCase()}</p>
          <Table rows={d.events} cols={[
            ['Время', (e) => e.timestamp.replace('T', ' ').slice(0, 16)], ['Событие', (e) => EVENTS[e.event_type]],
            ['Откуда', (e) => names[e.from_institution] || '—'], ['Куда', (e) => names[e.to_institution] || '—'], ['Примечание', (e) => esc(e.note)]]} />
        </>
      )}
    </Panel>
  )
}

export function Report() {
  const { data: r } = useLoad(() => api('/reports/summary'))
  if (!r) return <Loading />
  const pair = (o) => Object.entries(o).map(([k, v]) => ({ id: k, k, v }))
  return (
    <>
      <Panel title="Единицы по статусам"><Table rows={pair(r.units_by_status)} cols={[['Статус', (x) => t(x.k)], ['Количество', (x) => x.v]]} /></Panel>
      <Panel title="Заявки по статусам"><Table rows={pair(r.requests_by_status)} cols={[['Статус', (x) => t(x.k)], ['Количество', (x) => x.v]]} /></Panel>
      <Panel title="Время выполнения заявок">
        <dl className="facts">
          <div><dt>Выполнено заявок с замером</dt><dd>{r.request_turnaround.completed_requests}</dd></div>
          <div><dt>Среднее время</dt><dd>{r.request_turnaround.average_hours == null ? '—' : `${r.request_turnaround.average_hours} ч`}</dd></div>
          <div><dt>Медианное время</dt><dd>{r.request_turnaround.median_hours == null ? '—' : `${r.request_turnaround.median_hours} ч`}</dd></div>
        </dl>
        <p className="muted" style={{ marginTop: 8 }}>Считается от создания до закрытия выполненной заявки; новые закрытия попадут в отчёт автоматически.</p>
      </Panel>
      <p className={r.expired_not_discarded ? 'bad' : 'good'}>Просроченных, но не списанных единиц: {r.expired_not_discarded}</p>
    </>
  )
}

export function MapView() {
  const { data, loading } = useLoad(() => api('/map'))
  if (loading || !data) return <Loading />
  const places = [
    ...data.institutions.map((x) => ({ ...x, kind: x.type })),
    ...data.requests.map((x) => ({ ...x, kind: 'request', lon: x.lon + 0.012, lat: x.lat + 0.008 })),
    ...data.donor_clusters.map((x, i) => ({ ...x, id: `donors-${i}`, kind: 'donor' })),
  ]
  if (!places.length) return <Panel title="Карта"><p className="empty">Нет объектов для отображения.</p></Panel>
  const lons = places.map((x) => x.lon), lats = places.map((x) => x.lat)
  const minLon = Math.min(...lons), maxLon = Math.max(...lons), minLat = Math.min(...lats), maxLat = Math.max(...lats)
  const dx = Math.max(maxLon - minLon, 0.04), dy = Math.max(maxLat - minLat, 0.04)
  const position = (p) => ({ x: 50 + (p.lon - minLon) / dx * 900, y: 50 + (maxLat - p.lat) / dy * 500 })
  return (
    <Panel title="Карта региона">
      <p className="muted" style={{ marginBottom: 10 }}>Станции, больницы, открытые заявки и анонимные кластеры доноров. Координаты доноров округлены, показываются только группы от 3 человек.</p>
      <div className="map-frame">
        <svg viewBox="0 0 1000 600" role="img" aria-label="Карта учреждений, заявок и обезличенных групп доноров">
          {[1, 2, 3, 4].map((n) => <g key={n} className="map-grid"><path d={`M ${n * 200} 0 V 600`} /><path d={`M 0 ${n * 120} H 1000`} /></g>)}
          {places.map((p) => {
            const at = position(p)
            return <g key={`${p.kind}-${p.id}`} className={`map-marker ${p.kind}`} transform={`translate(${at.x} ${at.y})`}>
              <title>{p.kind === 'donor' ? `Доноры: ${p.count}` : p.kind === 'request' ? `Заявка №${p.id}: ${p.hospital}` : p.name}</title>
              {p.kind === 'donor' ? <><circle r={Math.min(28, 12 + p.count / 5)} /><text y="4">{p.count}</text></>
                : <><circle r={p.kind === 'request' ? 12 : 9} /><text y="4">{p.kind === 'station' ? 'С' : p.kind === 'hospital' ? 'Б' : '!'}</text></>}
            </g>
          })}
        </svg>
      </div>
      <div className="map-legend"><span className="station">Станция</span><span className="hospital">Больница</span><span className="request">Открытая заявка</span><span className="donor">Доноры (число в ячейке)</span></div>
    </Panel>
  )
}
