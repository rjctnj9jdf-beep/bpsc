import React, { useState } from 'react'
import { api } from '../api.js'
import { Field, Loading, Panel, Table, useAct, useLoad } from '../components/ui.jsx'
import { t } from '../labels.js'

export function Users({ institutions }) {
  const act = useAct()
  const { data: users, reload } = useLoad(() => api('/admin/users'))
  const [f, setF] = useState({ email: '', password: '', role: 'station', institution_id: '' })
  if (!users) return <Loading />
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const create = async (e) => {
    e.preventDefault()
    const inst = f.role === 'admin' ? null : +(f.institution_id || institutions[0]?.id)
    if (await act(() => api('/admin/users', 'POST', { email: f.email, password: f.password, role: f.role, institution_id: inst }), 'Пользователь создан')) { setF({ ...f, email: '', password: '' }); reload() }
  }
  return (
    <>
      <Panel title="Пользователи">
        <Table rows={users} cols={[
          ['№', (x) => x.id], ['Email', (x) => x.email], ['Роль', (x) => t(x.role)], ['Неудачных входов', (x) => x.failed_attempts], ['Активен', (x) => (x.active ? 'да' : 'нет')],
          ['', (x) => <button className="btn sm alt" onClick={() => act(() => api('/admin/users/' + x.id, 'PATCH', { active: !x.active }), 'Сохранено').then(reload)}>{x.active ? 'Заблокировать' : 'Разблокировать'}</button>]]} />
      </Panel>
      <Panel title="Новый сотрудник">
        <form onSubmit={create}>
          <div className="grid">
            <Field label="Email" id="e"><input id="e" type="email" value={f.email} onChange={set('email')} required /></Field>
            <Field label="Пароль" id="p"><input id="p" type="password" autoComplete="new-password" value={f.password} onChange={set('password')} required minLength={8} /></Field>
            <Field label="Роль" id="ro"><select id="ro" value={f.role} onChange={set('role')}><option value="station">Станция</option><option value="hospital">Больница</option><option value="admin">Администратор</option></select></Field>
            {f.role !== 'admin' && <Field label="Учреждение" id="in"><select id="in" value={f.institution_id} onChange={set('institution_id')}>{institutions.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</select></Field>}
          </div>
          <button className="btn" type="submit" style={{ marginTop: 14 }}>Создать</button>
        </form>
      </Panel>
    </>
  )
}

export function Audit() {
  const { data: a } = useLoad(() => api('/audit'))
  if (!a) return <Loading />
  return (
    <Panel title="Журнал аудита">
      <Table rows={a} cols={[['Время', (x) => x.timestamp.replace('T', ' ').slice(0, 19)], ['Пользователь №', (x) => x.actor_id], ['Действие', (x) => x.action], ['Объект', (x) => x.target]]} />
    </Panel>
  )
}
