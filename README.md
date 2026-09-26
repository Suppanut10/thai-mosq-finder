# หามัสยิด — Mosque Finder TH

เว็บหามัสยิดและสุเหร่าที่จดทะเบียนในประเทศไทย สำหรับมุสลิมที่เดินทางท่องเที่ยว
เป็นเว็บ static ล้วน (ไม่มี backend) deploy ฟรีบน GitHub Pages

- เลือกจังหวัด → เห็นรายการและแผนที่
- ปุ่ม **ใกล้ฉัน** → เรียงตามระยะทางจากตำแหน่งปัจจุบัน
- ปุ่ม **นำทาง** → เปิด Google Maps
- ใช้งานบนมือถือได้

## แหล่งข้อมูล

| ข้อมูล | ที่มา |
|---|---|
| รายชื่อมัสยิด (ชื่อ ตำบล อำเภอ จังหวัด) | [กรมการศาสนา — รายชื่อศาสนสถาน (มัสยิด)](https://catalog.dra.go.th/dataset/abd7a6de-ddb7-4f81-a64f-092f98b58c20) ปี 2565 |
| พิกัดมัสยิด, ขอบเขตตำบล/อำเภอ, แผนที่ | © ผู้ร่วมให้ข้อมูล [OpenStreetMap](https://www.openstreetmap.org/copyright) (ODbL) |

ไฟล์ของกรมการศาสนา **ไม่มีพิกัด** สคริปต์จึงจับคู่ชื่อกับมัสยิดใน OpenStreetMap
ตอนนี้มีเพียงราว 4% ที่ได้ตำแหน่งจริง ที่เหลือใช้ตำแหน่งกลางตำบล/อำเภอ (field `coord_source` บอกว่ามาจากไหน)
และบนเว็บ ปุ่มนำทางของรายการเหล่านี้จะให้ Google Maps ค้นหาด้วยชื่อ + ตำบล + อำเภอแทน

> อยากให้ข้อมูลแม่นขึ้น? ช่วยเพิ่มมัสยิดใน [OpenStreetMap](https://www.openstreetmap.org) โดยใส่แท็ก
> `amenity=place_of_worship`, `religion=muslim` และ `name=มัสยิด...` แล้วรันสคริปต์ใหม่ด้วย `--refresh-osm`

## โครงสร้าง

```
build_mosque_data.py       XLSX + OpenStreetMap -> data/
ms_3028_04-001.xlsx        ไฟล์จากกรมการศาสนา
osm_*.json                 cache ผล query OpenStreetMap
data/                      ผลลัพธ์ (commit ไว้ เว็บใช้ไฟล์นี้ตอน build)
  index.json               รายชื่อจังหวัด + จำนวน
  provinces/<slug>.json    มัสยิดแต่ละจังหวัด
  review.csv               รายการที่ควรให้คนตรวจ
web/                       เว็บ (Vite + vanilla JS + Leaflet)
.github/workflows/         deploy ขึ้น GitHub Pages อัตโนมัติ
```

## รันบนเครื่อง

ต้องมี Python 3.9+ และ Node.js 20+

```sh
# สร้างข้อมูล (ข้ามได้ถ้าไม่ได้เปลี่ยนข้อมูล เพราะ data/ commit ไว้แล้ว)
python3 -m venv .venv && source .venv/bin/activate
pip install pandas openpyxl requests rapidfuzz
python build_mosque_data.py --xlsx ms_3028_04-001.xlsx

# เว็บ
cd web
npm install
npm run dev        # เปิด http://localhost:5173
npm run build      # ได้ไฟล์ใน web/dist
```

## อัปเดตข้อมูลเมื่อกรมการศาสนาออกไฟล์ปีใหม่

1. **ดาวน์โหลดไฟล์ใหม่** จาก [catalog.dra.go.th](https://catalog.dra.go.th/dataset/abd7a6de-ddb7-4f81-a64f-092f98b58c20)
   เลือกไฟล์ XLSX ที่เป็น *รายชื่อ* มัสยิด (ไม่ใช่ไฟล์สถิติจำนวน) แล้ววางไว้ในโฟลเดอร์โปรเจกต์
   หรือไม่ต้องใส่ `--xlsx` สคริปต์จะดาวน์โหลดผ่าน API ให้เอง

2. **รันสคริปต์** พร้อมดึงข้อมูล OpenStreetMap ใหม่ (OSM มีคนเพิ่มมัสยิดอยู่เรื่อยๆ)
   ```sh
   source .venv/bin/activate
   python build_mosque_data.py --xlsx <ไฟล์ใหม่>.xlsx --refresh-osm
   ```
   `--refresh-osm` จะ query Overpass ใหม่ทั้ง 3 ชุด ใช้เวลาประมาณ 15 นาที
   (ชุด `osm_membership.json` ช้าที่สุด ~11 นาที) ถ้า Overpass ตอบ 429/504 สคริปต์จะรอแล้วลองใหม่เอง

3. **ถ้าสคริปต์หาคอลัมน์ไม่เจอ** (กรมฯ เปลี่ยนชื่อหัวตาราง) ระบุเองได้ เช่น
   ```sh
   python build_mosque_data.py --xlsx new.xlsx --col-name "ชื่อมัสยิด" --col-district "อำเภอ" --col-subdistrict "ตำบล"
   ```

4. **ตรวจผล**
   - ดูสรุปท้ายสคริปต์: จำนวน `matched` / `review` / `unmatched` และ `ที่มาของพิกัด` ไม่ควรลดลงจากเดิมมาก
   - ถ้ามี `[warn] ชื่อจังหวัดไม่ตรงกับ OSM` ให้เพิ่มชื่อใน `PROVINCE_ALIASES` ในสคริปต์
   - เปิด `data/review.csv` ด้วย Excel ดูรายการ `review` / `ambiguous` ว่าจับคู่ถูกไหม

5. **แก้ปีในเว็บ** ข้อความ "ปี 2565" อยู่ใน `web/index.html` (footer) เปลี่ยนเป็นปีของไฟล์ใหม่

6. **ลองบนเครื่อง** `cd web && npm run dev` เลือกจังหวัดสัก 2–3 จังหวัดดูว่าข้อมูลขึ้น

7. **commit และ push** เว็บจะ deploy ใหม่เองภายในไม่กี่นาที
   ```sh
   git add data/ osm_*.json web/index.html <ไฟล์ใหม่>.xlsx
   git commit -m "อัปเดตข้อมูลมัสยิดปี 25xx"
   git push
   ```

## Deploy

ทุกครั้งที่ push เข้า branch `main` GitHub Actions ([.github/workflows/deploy.yml](.github/workflows/deploy.yml))
จะ build เว็บใน `web/` แล้ว publish `web/dist` ขึ้น GitHub Pages
สั่ง deploy เองได้ที่แท็บ **Actions → Deploy to GitHub Pages → Run workflow**

## สัญญาอนุญาต

ข้อมูลพิกัดและแผนที่มาจาก OpenStreetMap ภายใต้ [ODbL](https://opendatacommons.org/licenses/odbl/)
ต้องแสดง "© ผู้ร่วมให้ข้อมูล OpenStreetMap" ทุกครั้งที่นำข้อมูลใน `data/` ไปใช้ต่อ
