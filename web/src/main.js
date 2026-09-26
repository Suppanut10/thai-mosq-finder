import './style.css'
import { loadIndex, loadProvince, provincesNear } from './data.js'
import { distanceKm, formatDistance, isExact, directionsUrl, placeLabel } from './geo.js'
import { initMap, renderMarkers, fitToResults, focusMosque, showUser, refreshSize } from './map.js'

const $ = (id) => document.getElementById(id)
const ui = {
  province: $('province'),
  search: $('search'),
  nearMe: $('near-me'),
  status: $('status'),
  list: $('list'),
  layout: document.querySelector('.layout'),
  tabList: $('tab-list'),
  tabMap: $('tab-map'),
}

const state = { index: [], rows: [], user: null, query: '', limit: 0 }
const SOURCE_NOTE = { subdistrict_center: 'ตำแหน่งกลางตำบล', district_center: 'ตำแหน่งกลางอำเภอ', province_center: 'ตำแหน่งกลางจังหวัด' }

const store = {
  get: (k) => { try { return localStorage.getItem(k) } catch { return null } },
  set: (k, v) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } },
}

// --------------------------------------------------------------------------- view tabs (มือถือ)
function setView(view) {
  ui.layout.dataset.view = view
  for (const [tab, v] of [[ui.tabList, 'list'], [ui.tabMap, 'map']]) {
    const on = v === view
    tab.setAttribute('aria-selected', String(on))
    tab.tabIndex = on ? 0 : -1
  }
  if (view === 'map') requestAnimationFrame(refreshSize)
}
ui.tabList.addEventListener('click', () => setView('list'))
ui.tabMap.addEventListener('click', () => setView('map'))
document.querySelector('.tabs').addEventListener('keydown', (e) => {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  const next = ui.layout.dataset.view === 'list' ? 'map' : 'list'
  setView(next)
  ;(next === 'map' ? ui.tabMap : ui.tabList).focus()
})

// --------------------------------------------------------------------------- list
function matches(m, q) {
  if (!q) return true
  return [m.name, m.subdistrict, m.district, m.province].some((s) => s && s.toLowerCase().includes(q))
}

function card(m) {
  const exact = isExact(m)
  const li = document.createElement('li')
  li.className = 'card'

  const head = document.createElement('div')
  head.className = 'card-head'
  const h = document.createElement('h2')
  h.textContent = m.name
  const badge = document.createElement('span')
  badge.className = `badge ${m.type === 'สุเหร่า' ? 'badge-surau' : ''}`
  badge.textContent = m.type || 'มัสยิด'
  head.append(h, badge)

  const place = document.createElement('p')
  place.className = 'place'
  place.textContent = placeLabel(m)

  const meta = document.createElement('p')
  meta.className = 'meta'
  if (m._dist != null) {
    const d = document.createElement('span')
    d.className = 'dist'
    d.textContent = formatDistance(m._dist, !exact)
    meta.append(d)
  }
  const prec = document.createElement('span')
  prec.className = exact ? 'prec prec-exact' : 'prec'
  prec.textContent = exact ? 'ตำแหน่งจริง' : SOURCE_NOTE[m.coord_source] || 'ไม่มีพิกัด'
  meta.append(prec)

  const actions = document.createElement('div')
  actions.className = 'actions'
  const nav = document.createElement('a')
  nav.className = 'btn btn-primary btn-sm'
  nav.href = directionsUrl(m)
  nav.target = '_blank'
  nav.rel = 'noopener'
  nav.textContent = exact ? 'นำทาง' : 'ค้นหาใน Google Maps'
  nav.setAttribute('aria-label', `${nav.textContent}ไป${m.name} (เปิดแท็บใหม่)`)
  actions.append(nav)
  if (m.lat != null) {
    const show = document.createElement('button')
    show.type = 'button'
    show.className = 'btn btn-ghost btn-sm'
    show.textContent = 'ดูบนแผนที่'
    show.setAttribute('aria-label', `ดู${m.name}บนแผนที่`)
    show.addEventListener('click', () => {
      setView('map')
      requestAnimationFrame(() => focusMosque(m))
    })
    actions.append(show)
  }

  li.append(head, place, meta, actions)
  return li
}

const PAGE = 100 // โหมดใกล้ฉันโหลดหลายจังหวัด (2,000+ แห่ง) ไม่ต้องสร้างการ์ดทีเดียวทั้งหมด

function moreButton(rows) {
  const li = document.createElement('li')
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.className = 'btn btn-ghost more'
  btn.textContent = `แสดงเพิ่มอีก ${Math.min(PAGE, rows.length - state.limit)} แห่ง (เหลือ ${(rows.length - state.limit).toLocaleString('th')})`
  btn.addEventListener('click', () => {
    const from = state.limit
    state.limit += PAGE
    li.replaceWith(...rows.slice(from, state.limit).map(card), ...(rows.length > state.limit ? [moreButton(rows)] : []))
    ui.list.children[from]?.querySelector('a, button')?.focus()
  })
  li.append(btn)
  return li
}

function render({ fit = false } = {}) {
  const q = state.query.trim().toLowerCase()
  const rows = state.rows.filter((m) => matches(m, q))
  state.limit = PAGE
  ui.list.replaceChildren(...rows.slice(0, PAGE).map(card), ...(rows.length > PAGE ? [moreButton(rows)] : []))
  renderMarkers(rows)
  if (fit) fitToResults(state.user)

  if (!state.rows.length) return
  const exact = rows.filter(isExact).length
  const near = state.user ? ' เรียงจากใกล้ที่สุด' : ''
  ui.status.textContent = rows.length
    ? `พบ ${rows.length.toLocaleString('th')} แห่ง${q ? ` ที่ตรงกับ “${state.query.trim()}”` : ''}${near} · มีตำแหน่งจริง ${exact} แห่ง`
    : `ไม่พบมัสยิดที่ตรงกับ “${state.query.trim()}”`
}

// --------------------------------------------------------------------------- actions
async function showProvince(name) {
  const entry = state.index.find((p) => p.province === name)
  if (!entry) return
  state.user = null
  ui.status.textContent = `กำลังโหลด${entry.province}…`
  try {
    const rows = await loadProvince(entry)
    if (ui.province.value !== name) return // ผู้ใช้เปลี่ยนจังหวัดระหว่างโหลด
    state.rows = rows.map((m) => ({ ...m, _dist: null }))
    store.set('province', name)
    render({ fit: true })
  } catch (err) {
    ui.status.textContent = `${err.message} — ลองใหม่อีกครั้ง`
  }
}

function getPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error('เบราว์เซอร์นี้ไม่รองรับการหาตำแหน่ง'))
    navigator.geolocation.getCurrentPosition(
      (p) => resolve([p.coords.latitude, p.coords.longitude]),
      (e) => reject(new Error(e.code === 1 ? 'ไม่ได้รับอนุญาตให้ใช้ตำแหน่ง — เปิดสิทธิ์ตำแหน่งในเบราว์เซอร์ หรือเลือกจังหวัดแทน' : 'หาตำแหน่งไม่สำเร็จ — ลองใหม่ หรือเลือกจังหวัดแทน')),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
    )
  })
}

async function nearMe() {
  ui.nearMe.disabled = true
  ui.nearMe.setAttribute('aria-busy', 'true')
  ui.status.textContent = 'กำลังหาตำแหน่งของคุณ…'
  try {
    const pos = await getPosition()
    const near = provincesNear(state.index, pos)
    ui.status.textContent = `กำลังโหลด ${near.map((p) => p.province).join(', ')}…`
    const lists = await Promise.all(near.map(loadProvince))
    state.user = pos
    state.rows = lists.flat()
      .map((m) => ({ ...m, _dist: m.lat != null ? distanceKm(pos, [m.lat, m.lng]) : null }))
      .sort((a, b) => (a._dist ?? Infinity) - (b._dist ?? Infinity))
    ui.province.value = ''
    showUser(pos)
    render()
    fitToResults(pos, state.rows.slice(0, 15))
    ui.status.textContent = `${ui.status.textContent} · จาก ${near.map((p) => p.province).join(', ')}`
  } catch (err) {
    ui.status.textContent = err.message
  } finally {
    ui.nearMe.disabled = false
    ui.nearMe.removeAttribute('aria-busy')
  }
}

// --------------------------------------------------------------------------- init
async function init() {
  initMap($('map'))
  try {
    state.index = await loadIndex()
  } catch (err) {
    ui.status.textContent = err.message
    return
  }
  const total = state.index.reduce((s, p) => s + p.count, 0)
  if (!store.get('province')) {
    ui.status.textContent = `มัสยิดจดทะเบียน ${total.toLocaleString('th')} แห่งใน ${state.index.length} จังหวัด — เลือกจังหวัด หรือกด “ใกล้ฉัน”`
  }
  ui.province.replaceChildren(
    new Option('เลือกจังหวัด', ''),
    ...state.index.map((p) => new Option(`${p.province} (${p.count})`, p.province)),
  )
  ui.province.disabled = false
  ui.search.disabled = false

  ui.province.addEventListener('change', () => ui.province.value && showProvince(ui.province.value))
  ui.nearMe.addEventListener('click', nearMe)
  let t
  ui.search.addEventListener('input', () => {
    clearTimeout(t)
    t = setTimeout(() => { state.query = ui.search.value; render({ fit: true }) }, 150)
  })
  $('controls').addEventListener('submit', (e) => e.preventDefault())

  const last = store.get('province')
  if (last && state.index.some((p) => p.province === last)) {
    ui.province.value = last
    showProvince(last)
  }
}

init()
