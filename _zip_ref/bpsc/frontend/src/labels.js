const L = {
  red_cells: 'Эритроциты', platelets: 'Тромбоциты', plasma: 'Плазма', whole_blood: 'Цельная кровь',
  testing: 'Ожидает тестирования', tested: 'Протестирована', stored: 'На хранении', reserved: 'В резерве', transfused: 'Перелита', discarded: 'Списана',
  open: 'Открыта', partial: 'Частично', fulfilled: 'Выполнена', cancelled: 'Отменена',
  sent: 'Ждёт ответа', accepted: 'Принято', declined: 'Отклонено',
  booked: 'Записан', completed: 'Сдал', no_show: 'Не пришёл',
  routine: 'Плановая', urgent: 'Срочная', critical: 'Критическая',
  donor: 'Донор', station: 'Станция', hospital: 'Больница', admin: 'Администратор',
}
export const t = (k) => L[k] || k
export const COMPONENTS = ['red_cells', 'platelets', 'plasma', 'whole_blood']
export const grp = (r) => `${r.blood_group}${r.rh}`

const TZ = 'Asia/Almaty'
const fmt = (opts) => new Intl.DateTimeFormat('ru-RU', { timeZone: TZ, ...opts })
const F = {
  dt: fmt({ day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' }),
  d: fmt({ day: 'numeric', month: 'long' }),
  dy: fmt({ day: 'numeric', month: 'long', year: 'numeric' }),
  wd: fmt({ weekday: 'short' }),
  iso: new Intl.DateTimeFormat('en-CA', { timeZone: TZ }),
}
export const fmtDateTime = (iso) => F.dt.format(new Date(iso))
export const fmtDate = (iso) => F.dy.format(new Date(iso))
export const fmtDay = (ymd) => F.d.format(new Date(ymd + 'T12:00:00Z'))
export const weekday = (ymd) => F.wd.format(new Date(ymd + 'T12:00:00Z'))
export const dayNum = (ymd) => Number(ymd.slice(8))
export const todayYmd = () => F.iso.format(new Date())
export const addDays = (ymd, n) => new Date(Date.parse(ymd + 'T12:00:00Z') + n * 864e5).toISOString().slice(0, 10)
export const isSunday = (ymd) => new Date(ymd + 'T12:00:00Z').getUTCDay() === 0
export const ymdOf = (iso) => F.iso.format(new Date(iso))
export const hoursLabel = (u) =>
  u.expired ? { text: 'истёк', cls: 'bad' } : u.expiring ? { text: `${u.hours_left} ч`, cls: 'warn' } : { text: `${Math.round(u.hours_left / 24)} дн.`, cls: '' }
export const plural = (n, [one, few, many]) => {
  const m = n % 100, d = n % 10
  return m > 10 && m < 20 ? many : d === 1 ? one : d > 1 && d < 5 ? few : many
}
