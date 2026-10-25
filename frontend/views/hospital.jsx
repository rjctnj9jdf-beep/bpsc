import React, { useState } from 'react'
import { api } from '../api.js'
import { BarChart, Field, Loading, Panel, Table, useAct, useLoad } from '../components/ui.jsx'
import { COMPONENTS, grp, t } from '../labels.js'

export function NewRequest({ goTo }) {
  const act = useAct()
  const [f, setF] = useState({ component: 'red_cells', blood_group: 'O', rh: '+', units_needed: 2, urgency: 'urgent' })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const submit = async (e) => {
    e.preventDefault()
    const r = await act(() => api('/requests', 'POST', { ...f, units_needed: +f.units_needed }),
      (x) => `Заявка №${x.request_id}: в наличии ${x.available_units}, оповещено доноров ${x.notified_donors}`)
    if (r) goTo('reqs')
  }
  return (
    <Panel title="Новая заявка">
      <form onSubmit={submit}>
        <div className="grid">
          <Field label="Компонент" id="c"><select id="c" value={f.component} onChange={set('component')}>{COMPONENTS.map((c) => <option key={c} value={c}>{t(c)}</option>)}</select></Field>
          <Field label="Группа" id="g"><select id="g" value={f.blood_group} onChange={set('blood_group')}>{['O', 'A', 'B', 'AB'].map((x) => <option key={x}>{x}</option>)}</select></Field>
          <Field label="Резус" id="r"><select id="r" value={f.rh} onChange={set('rh')}>{['+', '-'].map((x) => <option key={x}>{x}</option>)}</select></Field>
          <Field label="Количество единиц" id="n"><input id="n" type="number" min="1" max="50" value={f.units_needed} onChange={set('units_needed')} required /></Field>
          <Field label="Срочность" id="u">
            <select id="u" value={f.urgency} onChange={set('urgency')}>
              <option value="critical">Критическая</option><option value="urgent">Срочная</option><option value="routine">Плановая</option>
            </select>
          </Field>
        </div>
        <button className="btn" type="submit" style={{ marginTop: 14 }}>Создать заявку</button>
        <p className="muted" style={{ marginTop: 10 }}>Если запаса в регионе не хватает, подходящие доноры оповещаются автоматически.</p>
      </form>
    </Panel>
  )
}

export function Forecast({ me }) {
  const { data: f } = useLoad(() => api('/forecast/' + me.institution.id))
  if (!f) return <Loading />
  return (
    <Panel title="Ожидаемая потребность на 7 дней">
      <p className="muted" style={{ marginBottom: 8 }}>Среднее по заявкам за последние 4 недели.</p>
      {f.length > 0 && <BarChart label="Прогноз потребности по компонентам и группам" items={f.map((x) => ({
        label: `${t(x.component)} ${grp(x)}`, value: x.expected_units_7d,
      }))} />}
      <Table rows={f.map((x, i) => ({ ...x, id: i }))} cols={[['Компонент', (x) => t(x.component)], ['Группа', grp], ['Ожидается, ед.', (x) => x.expected_units_7d]]} />
    </Panel>
  )
}
