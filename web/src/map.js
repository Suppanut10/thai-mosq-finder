// แผนที่ Leaflet + tile OpenStreetMap
// จุดจริง = วงกลมทึบ, จุดประมาณ (กลางตำบล/อำเภอ) = รวมเป็นกลุ่มต่อพิกัดเพราะหลายแห่งซ้อนกันที่จุดเดียว
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { isExact, directionsUrl, placeLabel } from './geo.js'

const THAILAND = [[5.6, 97.3], [20.5, 105.7]]
const APPROX_NOTE = { subdistrict_center: 'กลางตำบล', district_center: 'กลางอำเภอ', province_center: 'กลางจังหวัด' }

let map, layer, userLayer
const byId = new Map() // id -> { marker, group? }

const el = (tag, props = {}, ...children) => {
  const e = Object.assign(document.createElement(tag), props)
  e.append(...children)
  return e
}

function navLink(m) {
  return el('a', { href: directionsUrl(m), target: '_blank', rel: 'noopener', className: 'popup-nav', textContent: 'นำทาง ↗' })
}

function exactPopup(m) {
  return el('div', { className: 'popup' },
    el('strong', { textContent: m.name }),
    el('div', { className: 'popup-place', textContent: placeLabel(m) }),
    navLink(m))
}

function groupPopup(items) {
  const src = APPROX_NOTE[items[0].coord_source] || 'โดยประมาณ'
  const ul = el('ul', { className: 'popup-list' })
  for (const m of items.slice(0, 12)) {
    ul.append(el('li', {}, el('span', { textContent: m.name }), ' ', navLink(m)))
  }
  if (items.length > 12) ul.append(el('li', { className: 'muted', textContent: `และอีก ${items.length - 12} แห่ง` }))
  return el('div', { className: 'popup' },
    el('strong', { textContent: `${items.length} แห่ง · ตำแหน่ง${src}` }),
    el('div', { className: 'popup-place', textContent: `อ.${items[0].district} จ.${items[0].province}` }),
    ul)
}

export function initMap(container) {
  map = L.map(container, { zoomControl: true, attributionControl: true }).fitBounds(THAILAND)
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map)
  layer = L.featureGroup().addTo(map)
  userLayer = L.layerGroup().addTo(map)
  return map
}

export function renderMarkers(rows) {
  layer.clearLayers()
  byId.clear()
  const groups = new Map()
  for (const m of rows) {
    if (m.lat == null) continue
    if (isExact(m)) {
      const marker = L.circleMarker([m.lat, m.lng], { radius: 8, className: 'mk-exact', weight: 2 })
        .bindPopup(() => exactPopup(m))
        .addTo(layer)
      byId.set(m.id, { marker })
    } else {
      const k = `${m.lat},${m.lng}`
      if (!groups.has(k)) groups.set(k, [])
      groups.get(k).push(m)
    }
  }
  for (const items of groups.values()) {
    const n = items.length
    const size = n > 99 ? 40 : n > 9 ? 34 : 28
    const marker = L.marker([items[0].lat, items[0].lng], {
      icon: L.divIcon({ className: 'mk-approx', html: `<span>${n}</span>`, iconSize: [size, size] }),
      title: `${n} แห่ง ตำแหน่งโดยประมาณ`,
      keyboard: true,
    })
      .bindPopup(() => groupPopup(items), { maxHeight: 280 })
      .addTo(layer)
    for (const m of items) byId.set(m.id, { marker })
  }
}

let pendingFit = null

function applyFit(b) {
  // แผนที่ซ่อนอยู่ (แท็บรายการบนมือถือ) ขนาดเป็น 0 -> fit ตอนนี้จะได้ซูมผิด รอจนแสดงก่อน
  if (!map.getContainer().offsetWidth) return void (pendingFit = b)
  pendingFit = null
  map.fitBounds(b, { padding: [24, 24], maxZoom: 14 })
}

// rows ไม่ระบุ = ครอบทุกหมุด, ระบุ = ครอบเฉพาะรายการนั้น (เช่น 20 แห่งที่ใกล้ที่สุด)
export function fitToResults(extra, rows) {
  const b = rows
    ? L.latLngBounds(rows.filter((m) => m.lat != null).map((m) => [m.lat, m.lng]))
    : layer.getBounds()
  if (extra) b.extend(extra)
  if (b.isValid()) applyFit(b)
}

export function focusMosque(m) {
  const hit = byId.get(m.id)
  if (!hit) return
  pendingFit = null
  map.setView(hit.marker.getLatLng(), isExact(m) ? 16 : 13)
  hit.marker.openPopup()
}

export function showUser(pos) {
  userLayer.clearLayers()
  L.circleMarker(pos, { radius: 9, className: 'mk-user', weight: 3 }).bindTooltip('ตำแหน่งของคุณ').addTo(userLayer)
}

export function refreshSize() {
  if (!map) return
  map.invalidateSize()
  if (pendingFit) applyFit(pendingFit)
}
