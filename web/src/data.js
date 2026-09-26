// โหลด index.json ก่อน แล้วค่อยโหลดไฟล์จังหวัดเมื่อต้องใช้ (ไม่โหลดทั้งประเทศทีเดียว)
import { distanceKm } from './geo.js'

const base = `${import.meta.env.BASE_URL}data/`
const cache = new Map()

export async function loadIndex() {
  const res = await fetch(`${base}index.json`)
  if (!res.ok) throw new Error(`โหลดรายชื่อจังหวัดไม่ได้ (${res.status})`)
  const index = await res.json()
  return index.sort((a, b) => a.province.localeCompare(b.province, 'th'))
}

export function loadProvince(entry) {
  if (!cache.has(entry.file)) {
    const p = fetch(base + entry.file).then((res) => {
      if (!res.ok) throw new Error(`โหลดข้อมูล${entry.province}ไม่ได้ (${res.status})`)
      return res.json()
    })
    p.catch(() => cache.delete(entry.file)) // ให้ลองใหม่ได้
    cache.set(entry.file, p)
  }
  return cache.get(entry.file)
}

// จังหวัดที่ใกล้ที่สุด + จังหวัดข้างเคียง (ศูนย์กลางห่างไม่เกิน radiusKm) สูงสุด max จังหวัด
export function provincesNear(index, pos, { radiusKm = 120, max = 4 } = {}) {
  const ranked = index
    .filter((p) => p.center)
    .map((p) => ({ p, d: distanceKm(pos, p.center) }))
    .sort((a, b) => a.d - b.d)
  if (!ranked.length) return []
  const nearest = ranked[0]
  return [nearest, ...ranked.slice(1).filter((x) => x.d <= nearest.d + radiusKm)].slice(0, max).map((x) => x.p)
}
