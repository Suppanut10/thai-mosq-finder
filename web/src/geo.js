// ระยะทางและลิงก์นำทาง

const R = 6371 // km

export function distanceKm(a, b) {
  const toRad = (d) => (d * Math.PI) / 180
  const dLat = toRad(b[0] - a[0])
  const dLng = toRad(b[1] - a[1])
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

export function formatDistance(km, approx) {
  const s = km < 1 ? `${Math.round(km * 1000)} ม.` : `${km < 10 ? km.toFixed(1) : Math.round(km)} กม.`
  return approx ? `~${s}` : s
}

// พิกัดจริงของตัวมัสยิด (ไม่ใช่กลางตำบล/อำเภอ)
export const isExact = (m) => m.coord_source === 'osm' || m.coord_source === 'nominatim'

export function placeLabel(m) {
  const bkk = m.province === 'กรุงเทพมหานคร'
  const parts = []
  if (m.subdistrict) parts.push(`${bkk ? 'แขวง' : 'ต.'}${m.subdistrict}`)
  if (m.district) parts.push(`${bkk ? 'เขต' : 'อ.'}${m.district}`)
  if (!bkk) parts.push(`จ.${m.province}`)
  else parts.push(m.province)
  return parts.join(' ')
}

// พิกัดจริง -> นำทางตรงไปที่จุด, ประมาณ -> ให้ Google Maps ค้นด้วยชื่อ+ตำบล+อำเภอ
export function directionsUrl(m) {
  if (isExact(m)) {
    return `https://www.google.com/maps/dir/?api=1&destination=${m.lat},${m.lng}`
  }
  const prefix = /^(มัสยิด|สุเหร่า)/.test(m.name) ? '' : `${m.type || 'มัสยิด'}`
  const q = `${prefix}${m.name} ${placeLabel(m)}`
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`
}
