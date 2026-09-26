// copy ../data (ผลจาก build_mosque_data.py) -> public/data
// เพิ่ม center ของแต่ละจังหวัดใน index.json ไว้หาจังหวัดใกล้ผู้ใช้ (ปุ่ม "ใกล้ฉัน")
import { readFile, writeFile, mkdir, rm } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = path.dirname(fileURLToPath(import.meta.url))
const src = path.resolve(root, '../../data')
const dest = path.resolve(root, '../public/data')

const index = JSON.parse(await readFile(path.join(src, 'index.json'), 'utf8'))
await rm(dest, { recursive: true, force: true })
await mkdir(path.join(dest, 'provinces'), { recursive: true })

for (const p of index) {
  const raw = await readFile(path.join(src, p.file), 'utf8')
  const rows = JSON.parse(raw)
  const pts = rows.filter((r) => r.lat != null)
  p.center = pts.length
    ? [+(pts.reduce((s, r) => s + r.lat, 0) / pts.length).toFixed(4), +(pts.reduce((s, r) => s + r.lng, 0) / pts.length).toFixed(4)]
    : null
  await writeFile(path.join(dest, p.file), raw)
}
await writeFile(path.join(dest, 'index.json'), JSON.stringify(index))
console.log(`[data] copied ${index.length} provinces -> ${path.relative(process.cwd(), dest)}`)
