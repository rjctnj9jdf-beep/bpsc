import React, { useState } from 'react'
import { api } from '../api.js'
import { Field, Loading, Panel, Table, Tag, useAct, useLoad } from '../components/ui.jsx'
import { COMPONENTS, fmtDateTime, fmtDay, grp, t, todayYmd, ymdOf } from '../labels.js'

export function Donate() {
  const act = useAct()
  const { data: donors } = useLoad(() => api('/donors'))
  const [f, setF] = useState({ donor_id: '', component: 'red_cells', volume_ml: 450 })
  if (!donors) return <Loading />
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const submit = (e) => {
    e.preventDefault()
    act(() => api('/donations', 'POST', { donor_id: +(f.donor_id || donors[0]?.id), component: f.component, volume_ml: +f.volume_ml }), (r) => `Единица №${r.unit_id} на хранении`)
  }
  return (
    <Panel title="Регистрация донации">
      <form onSubmit={submit}>
        <div className="grid">
          <Field label="Донор (только давшие согласие)" id="d">
            <select id="d" value={f.donor_id} onChange={set('donor_id')}>
              {donors.map((x) => <option key={x.id} value={x.id}>#{x.id} {x.full_name}, {grp(x)}, последняя: {x.last_donation_date || 'нет'}</option>)}
            </select>
          </Field>
          <Field label="Компонент" id="c"><select id="c" value={f.component} onChange={set('component')}>{COMPONENTS.map((c) => <option key={c} value={c}>{t(c)}</option>)}</select></Field>
          <Field label="Объём, мл" id="v"><input id="v" type="number" min="50" max="1000" value={f.volume_ml} onChange={set('volume_ml')} /></Field>
        </div>
        <button className="btn" type="submit" style={{ marginTop: 14 }}>Записать донацию</button>
        <p className="muted" style={{ marginTop: 10 }}>После сдачи единица попадёт в очередь тестирования; хранение начнётся после успешного результата.</p>
      </form>
    </Panel>
  )
}

function VisitRow({ a, today, onDone }) {
  const act = useAct()
  const [ml, setMl] = useState(a.component === 'platelets' ? 250 : 450)
  const due = ymdOf(a.slot_at) <= today
  const call = (path, body, ok) => act(() => api(`/appointments/${a.id}/${path}`, 'POST', body), ok).then((r) => r && onDone())
  return (
    <tr>
      <td>{new Date(a.slot_at).toLocaleTimeString('ru-RU', { timeZone: 'Asia/Almaty', hour: '2-digit', minute: '2-digit' })}</td>
      <td>#{a.donor_id} {a.full_name}</td>
      <td>{grp(a)}</td>
      <td>{t(a.component)}</td>
      <td>{a.request_id ? <Tag kind="warn">по заявке №{a.request_id}</Tag> : <span className="muted">плановая</span>}</td>
      <td>
        {a.status !== 'booked' ? <Tag kind={a.status === 'completed' ? 'good' : 'bad'}>{t(a.status)}</Tag> : due ? (
          <span className="row">
            <input aria-label="Объём, мл" type="number" min="50" max="1000" value={ml} onChange={(e) => setMl(e.target.value)} style={{ width: 80 }} />
            <button className="btn sm" onClick={() => call('complete', { volume_ml: +ml }, (r) => `Донация принята, единица №${r.unit_id}`)}>Донор пришёл</button>
            <button className="btn sm alt" onClick={() => call('no-show', undefined, 'Отмечено: не пришёл')}>Не пришёл</button>
          </span>
        ) : <span className="muted">визит ещё не наступил</span>}
      </td>
    </tr>
  )
}

export function Visits() {
  const { data: rows, reload } = useLoad(() => api('/appointments'))
  if (!rows) return <Loading />
  const today = todayYmd()
  const days = [...new Set(rows.map((a) => ymdOf(a.slot_at)))]
  return (
    <>
      <Panel title="Записи доноров на вашу станцию">
        <p className="muted">Когда донор приходит, нажмите «Донор пришёл». Созданная единица поступит на тестирование, затем её можно будет поместить на хранение.</p>
      </Panel>
      {days.length === 0 && <Panel><p className="empty">Записей пока нет. Они появятся, когда доноры выберут время.</p></Panel>}
      {days.map((d) => (
        <Panel key={d} title={d === today ? `Сегодня, ${fmtDay(d)}` : fmtDay(d)}>
          <div className="scroll"><table>
            <thead><tr>{['Время', 'Донор', 'Группа', 'Компонент', 'Повод', ''].map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>{rows.filter((a) => ymdOf(a.slot_at) === d).map((a) => <VisitRow key={a.id} a={a} today={today} onDone={reload} />)}</tbody>
          </table></div>
        </Panel>
      ))}
    </>
  )
}

export function Rebalance() {
  const { data: r } = useLoad(() => api('/rebalance'))
  if (!r) return <Loading />
  return (
    <Panel title="Рекомендации по перераспределению">
      <Table rows={r.map((x, i) => ({ ...x, id: i }))} empty="Сейчас перераспределение не требуется." cols={[
        ['Откуда', (x) => x.from], ['Куда', (x) => x.to], ['Что', (x) => `${t(x.component)} ${grp(x)}`], ['Ед.', (x) => x.units],
        ['Единицы №', (x) => x.unit_ids.join(', ')], ['Причина', (x) => x.reason]]} />
    </Panel>
  )
}
