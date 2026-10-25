export function haversineKm(lat1, lon1, lat2, lon2) {
  const toR = (d) => (d * Math.PI) / 180
  const p1 = toR(lat1)
  const p2 = toR(lat2)
  const a = Math.sin((p2 - p1) / 2) ** 2
    + Math.cos(p1) * Math.cos(p2) * Math.sin((toR(lon2 - lon1)) / 2) ** 2
  return Math.round(6371 * 2 * Math.asin(Math.sqrt(a)) * 10) / 10
}

export const CITIES = [
  { name: 'Астана', lat: 51.128, lon: 71.430 },
  { name: 'Алматы', lat: 43.238, lon: 76.945 },
  { name: 'Шымкент', lat: 42.341, lon: 69.590 },
]

// Определение координат через браузер; ошибки передаются в toast(msg, true)
export function locate(setPos, toast) {
  if (!navigator.geolocation) return toast('Браузер не поддерживает геолокацию', true)
  navigator.geolocation.getCurrentPosition(
    (p) => setPos(+p.coords.latitude.toFixed(5), +p.coords.longitude.toFixed(5)),
    () => toast('Не удалось определить местоположение. Введите координаты вручную', true),
    { timeout: 8000 },
  )
}
