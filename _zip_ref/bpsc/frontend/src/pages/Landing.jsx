import React, { useEffect, useState } from 'react'
import { Logo } from '../components/ui.jsx'

const GROUPS = ['O', 'A', 'B', 'AB'].flatMap((g) => ['+', '-'].map((rh) => ({ blood_group: g, rh })))

function Bags({ stock }) {
  const [shown, setShown] = useState(false)
  useEffect(() => { const id = requestAnimationFrame(() => setShown(true)); return () => cancelAnimationFrame(id) }, [])
  const list = stock || GROUPS.map((g) => ({ ...g, count: null }))
  const max = Math.max(1, ...list.map((x) => x.count || 0))
  return (
    <div>
      <div className="bags" role="list" aria-label="Запасы по группам крови">
        {list.map((x) => {
          const n = x.count
          const lvl = n == null || !shown ? 0 : n === 0 ? 0 : Math.max(12, Math.round((n / max) * 100))
          const low = n != null && n < 3
          return (
            <div key={x.blood_group + x.rh} role="listitem" className={`bag ${x.rh === '-' ? 'neg' : ''} ${low ? 'low' : ''}`} style={{ '--lvl': lvl + '%' }}>
              <i />
              <b>{x.blood_group}{x.rh === '-' ? '−' : '+'}</b>
              <span>{n == null ? '—' : low ? `${n} ед., мало` : `${n} ед.`}</span>
            </div>
          )
        })}
      </div>
      <p className="bags-cap">Единиц на хранении по региону прямо сейчас. Заполнение показывает долю от самой большой позиции.</p>
    </div>
  )
}

const STEPS = [
  ['Врач создаёт заявку', 'Группа крови, компонент, количество и срочность. Обязательные поля проверяются сразу.'],
  ['Система смотрит запасы региона', 'Если подходящая единица есть, её можно зарезервировать и передать в больницу.'],
  ['Зовём только подходящих доноров', 'Группа, расстояние и интервал между донациями учитываются автоматически. Остальные ничего не получают.'],
  ['Станция фиксирует донацию', 'Донор сам выбирает станцию и время. После визита у единицы появляется путь до переливания или списания.'],
]
const ROLES = [
  ['Донор', 'Видит только запросы, которые ему подходят, и записывается на визит в удобное время. Знает, когда можно сдавать снова.'],
  ['Станция переливания', 'Ведёт запасы и сроки годности, принимает записавшихся доноров и регистрирует донации.'],
  ['Больница', 'Создаёт срочные заявки, видит наличие по региону и прогноз потребности на неделю.'],
  ['Администратор', 'Управляет учётными записями и смотрит журнал аудита: кто и когда открывал данные доноров.'],
]
const SAFE = [
  'Пароли хранятся только в виде хеша, ФИО и телефон доноров шифруются (AES-256)',
  'Больница видит доноров только обезличенно: группа, расстояние, давность донации',
  'Каждый просмотр персональных данных попадает в журнал аудита',
  'Журнал пути единицы крови только дополняется, записи нельзя изменить или удалить',
]

export default function Landing({ me }) {
  const [stats, setStats] = useState(null)
  useEffect(() => { fetch('/api/public/stats').then((r) => r.ok && r.json()).then(setStats).catch(() => {}) }, [])
  return (
    <div className="lp">
      <nav className="lp-nav" aria-label="Главная навигация">
        <Logo />
        <div className="links">
          <a href="#how" onClick={(e) => { e.preventDefault(); document.getElementById('how')?.scrollIntoView() }}>Как это работает</a>
          <a href="#roles" onClick={(e) => { e.preventDefault(); document.getElementById('roles')?.scrollIntoView() }}>Для кого</a>
          <a href="#safe" onClick={(e) => { e.preventDefault(); document.getElementById('safe')?.scrollIntoView() }}>Безопасность</a>
        </div>
        <div className="row">
          {me ? <a className="btn sm" href="#/app">Личный кабинет</a> : <>
            <a className="btn alt sm" href="#/login">Войти</a>
            <a className="btn sm" href="#/register">Стать донором</a>
          </>}
        </div>
      </nav>

      <header className="wrap hero">
        <div>
          <h1>Кровь нужной группы доходит до больницы вовремя</h1>
          <p className="lead">
            BPSC соединяет доноров, станции переливания и больницы. Платформа показывает запасы региона,
            зовёт на донацию только тех, кто подходит, и следит за каждой единицей крови до переливания.
          </p>
          <div className="row">
            <a className="btn lg" href="#/register">Стать донором</a>
            <a className="btn alt lg" href="#/login">Войти в систему</a>
          </div>
          {stats && (
            <p className="now">
              В системе {stats.stations} станции, {stats.hospitals} больниц и {stats.donors} доноров.
              Выполнено заявок: {stats.requests_fulfilled}.
            </p>
          )}
        </div>
        <Bags stock={stats?.stock_by_group} />
      </header>

      <section className="band" id="how">
        <div className="wrap">
          <h2>Что происходит после срочной заявки</h2>
          <ol className="steps">
            {STEPS.map(([b, p]) => <li key={b}><b>{b}</b><p>{p}</p></li>)}
          </ol>
        </div>
      </section>

      <section className="band" id="roles">
        <div className="wrap">
          <h2>Что получает каждый участник</h2>
          <dl className="roles">
            {ROLES.map(([r, d]) => <div key={r}><dt>{r}</dt><dd>{d}</dd></div>)}
          </dl>
        </div>
      </section>

      <section className="band" id="safe">
        <div className="wrap sec">
          <h2>Медицинские данные защищены</h2>
          <ul>{SAFE.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      </section>

      <section className="cta">
        <div className="wrap">
          <h2>Сдать кровь или плазму: регистрация и выбор времени займут пару минут</h2>
          <div className="row" style={{ justifyContent: 'center' }}>
            <a className="btn lg" href="#/register">Стать донором</a>
            <a className="btn alt lg" href="#/login">Войти</a>
          </div>
        </div>
      </section>

      <footer className="wrap foot">
        Blood &amp; Plasma Supply Chain. Учебный MVP: данные синтетические, интеграции с медицинскими системами нет.
      </footer>
    </div>
  )
}
