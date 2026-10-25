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
