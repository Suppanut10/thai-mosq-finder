#!/usr/bin/env python3
"""
build_mosque_data.py
ดึงรายชื่อมัสยิดที่จดทะเบียนจากกรมการศาสนา (XLSX) -> จับคู่ชื่อกับ OpenStreetMap เพื่อหาพิกัด
-> export JSON แยกตามจังหวัดสำหรับเว็บแอปหามัสยิด

ติดตั้ง:
    pip install pandas openpyxl requests rapidfuzz

ใช้งาน:
    python build_mosque_data.py                          # ดาวน์โหลดทุกอย่างอัตโนมัติ
    python build_mosque_data.py --xlsx mosques.xlsx      # ใช้ไฟล์ XLSX ที่โหลดเองแล้ว
    python build_mosque_data.py --geocode-fallback       # ใช้ Nominatim หาพิกัดที่จับคู่ไม่ได้ (ช้า 1 รายการ/วินาที)

ผลลัพธ์ (ในโฟลเดอร์ --out, ค่าเริ่มต้น ./data):
    index.json               รายชื่อจังหวัด + ชื่อไฟล์ + จำนวน
    provinces/<slug>.json    รายการมัสยิดของแต่ละจังหวัด
    all.json                 รวมทุกจังหวัด
    review.csv               รายการที่ต้องตรวจด้วยคน (คะแนนก้ำกึ่ง / ชื่อซ้ำ / ไม่พบพิกัด)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pandas as pd
import requests
from rapidfuzz import fuzz

# --------------------------------------------------------------------------- config
DRA_CKAN = "https://catalog.dra.go.th"
DRA_DATASET_ID = "abd7a6de-ddb7-4f81-a64f-092f98b58c20"  # รายชื่อศาสนสถาน (มัสยิด) ในประเทศไทย
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "mosque-finder-th/0.1"  # Overpass ตอบ 406 ถ้าใส่อีเมล placeholder — ใส่อีเมลจริงได้ตามนโยบาย OSM

MATCH_OK = 85        # คะแนน >= นี้ถือว่าจับคู่ได้
MATCH_REVIEW = 70    # คะแนนระหว่าง REVIEW..OK ให้คนตรวจ
AMBIGUOUS_GAP = 3    # อันดับ 1 กับ 2 ห่างกันไม่เกินนี้ = ชื่อกำกวม

OVERPASS_QUERY = """
[out:json][timeout:900];
area["ISO3166-1"="TH"][admin_level=2]->.th;
rel(area.th)[admin_level=4][boundary=administrative];
map_to_area->.provs;
foreach.provs->.p(
  .p out tags;
  nwr[amenity=place_of_worship][religion=muslim](area.p);
  out center tags;
);
"""

# ศูนย์กลางตำบล/อำเภอ ใช้เป็นพิกัดสำรองเมื่อหามัสยิดใน OSM ไม่เจอ
ADMIN_QUERY = """
[out:json][timeout:900];
area["ISO3166-1"="TH"][admin_level=2]->.th;
rel(area.th)[admin_level=4][boundary=administrative];
map_to_area->.provs;
foreach.provs->.p(
  .p out tags;
  rel(area.p)[boundary=administrative][admin_level~"^(6|8)$"];
  out center tags;
);
"""

# มัสยิด OSM แต่ละจุดอยู่ในอำเภอ/ตำบลไหน ใช้กันจับคู่ข้ามอำเภอ และจับคู่มัสยิดที่ไม่มีชื่อด้วยตำแหน่ง
MEMBERSHIP_QUERY = """
[out:json][timeout:900];
area["ISO3166-1"="TH"][admin_level=2]->.th;
rel(area.th)[boundary=administrative][admin_level~"^(6|8)$"];
map_to_area->.as;
foreach.as->.a(
  .a out tags;
  nwr[amenity=place_of_worship][religion=muslim](area.a);
  out ids;
);
"""

# --------------------------------------------------------------------------- text normalisation
TONE_MARKS = re.compile(r"[\u0E47-\u0E4E]")  # ็ ่ ้ ๊ ๋ ์ ํ ๎  (สะกดต่างกันบ่อย เช่น ดารุ้ล/ดารุล)
NON_WORD = re.compile(r"[^\u0E00-\u0E7Fa-z0-9]")
PREFIXES = ("มัสยิดกลางจังหวัด", "มัสยิดกลาง", "มัสยิด", "มัสยิต", "มัสญิด", "เสญิด", "สุเหร่า", "บาลาเซาะ", "บาลาย",
            "masjid", "masjit", "mosque", "surau")
# ทับศัพท์อาหรับสะกดได้หลายแบบ: ห์/ฮ์, ย/ญ, น/ณ, สระสั้น/ยาว, ะ ที่ใส่บ้างไม่ใส่บ้าง
CANON = str.maketrans({"ฮ": "ห", "ญ": "ย", "ณ": "น", "ษ": "ส", "ศ": "ส", "ฎ": "ด", "ฏ": "ต", "ฑ": "ท",
                       "ธ": "ท", "ถ": "ท", "ฆ": "ค", "ภ": "พ", "ฬ": "ล", "ี": "ิ", "ู": "ุ", "ะ": None})
# ไม่ใช่มัสยิด แต่ติดแท็ก religion=muslim ใน OSM (เช่น วัดถ้ำเขารูปช้าง, โรงเรียนสอนศาสนา)
NOT_MOSQUE = re.compile(r"^วัด|โรงเรียน|school|temple|church|สุสาน|กุโบร์|cemetery", re.I)
PROVINCE_ALIASES = {"กรุงเทพฯ": "กรุงเทพมหานคร", "กทม": "กรุงเทพมหานคร", "กทม.": "กรุงเทพมหานคร",
                    "กรุงเทพ": "กรุงเทพมหานคร"}


def clean_province(s: str) -> str:
    s = str(s or "").strip()
    s = re.sub(r"^(จังหวัด|จ\.)\s*", "", s)
    return PROVINCE_ALIASES.get(s, s)


def clean_district(s: str) -> str:
    s = str(s or "").strip()
    return re.sub(r"^(อำเภอ|อ\.|เขต|กิ่งอำเภอ)\s*", "", s)


def canon(s: str) -> str:
    s = str(s or "").lower().strip().replace("เเ", "แ")
    s = TONE_MARKS.sub("", s)
    s = NON_WORD.sub("", s).translate(CANON)
    return re.sub(r"(.)\1+", r"\1", s)  # ดาริสสลาม = ดาริสลาม


CANON_PREFIXES = tuple(canon(p) for p in PREFIXES)


def norm(s: str) -> str:
    s = canon(s)
    for p in CANON_PREFIXES:
        if s.startswith(p) and len(s) > len(p) + 1:
            s = s[len(p):]
            break
    return s


def variants(name: str) -> set[tuple[str, bool]]:
    """(key, อยู่ในวงเล็บไหม): ชื่อเต็ม, ชื่อที่ตัดวงเล็บออก, และชื่อในวงเล็บ เช่น 'มัสยิดบางหลวง (กุฎีขาว)'"""
    out = {(norm(name), False), (norm(re.sub(r"\(.*?(\)|$)", "", name)), False)}  # วงเล็บไม่ปิดก็ตัด
    out.update((norm(x), True) for x in re.findall(r"\((.*?)(?:\)|$)", name))
    out.update((k[len(BAN):], p) for k, p in list(out) if k.startswith(BAN) and len(k) > len(BAN) + 2)  # คลอแระ = บ้านคลอแระ
    return {v for v in out if len(v[0]) >= 2}


BAN = canon("บ้าน")
DIRECTION = re.compile("(" + "|".join(canon(w) for w in ("ออก", "ตก", "เหนือ", "ใต้", "ใน", "นอก", "บน", "ล่าง")) + ")$")


def name_score(a: set[tuple[str, bool]], b: set[tuple[str, bool]]) -> float:
    best = 0.0
    for x, xp in a:
        for y, yp in b:
            if xp and yp:  # ชื่อหมู่บ้านในวงเล็บตรงกันอย่างเดียว ไม่ได้แปลว่าเป็นมัสยิดเดียวกัน
                continue
            s = fuzz.ratio(x, y)
            if min(len(x), len(y)) >= 6:           # partial ช่วยกรณีชื่อยาว/มีคำต่อท้าย แต่กันชื่อสั้นจับมั่ว
                s = max(s, 0.9 * fuzz.partial_ratio(x, y))
            dx, dy = DIRECTION.search(x), DIRECTION.search(y)
            if (dx and dx[1]) != (dy and dy[1]):   # บ้านประกอบออก ≠ บ้านประกอบตก -> ให้คนตรวจ
                s = min(s, MATCH_OK - 5)
            best = max(best, s)
    return best


def detect_type(name: str) -> str:
    return "สุเหร่า" if "สุเหร่า" in str(name) else "มัสยิด"


# --------------------------------------------------------------------------- step 1: DRA xlsx
def download_dra_xlsx(dest: Path) -> Path:
    r = requests.get(f"{DRA_CKAN}/api/3/action/package_show", params={"id": DRA_DATASET_ID},
                     headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    res = [x for x in r.json()["result"]["resources"]
           if str(x.get("format", "")).lower() in ("xlsx", "xls") or str(x.get("url", "")).lower().endswith((".xlsx", ".xls"))]
    if not res:
        sys.exit("ไม่พบไฟล์ XLSX ใน dataset — ดาวน์โหลดเองแล้วใช้ --xlsx")
    # เลือกไฟล์ที่ชื่อบอกว่าเป็น 'รายชื่อ' ก่อน ไม่ใช่ 'สถิติจำนวน'
    res.sort(key=lambda x: ("รายชื่อ" not in (x.get("name") or ""), x.get("last_modified") or ""), reverse=False)
    url = res[0]["url"]
    print(f"[dra] ดาวน์โหลด {res[0].get('name')} <- {url}")
    f = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
    f.raise_for_status()
    dest.write_bytes(f.content)
    return dest


COL_RULES = {
    "name": lambda h: ("ชื่อ" in h and ("มัสยิด" in h or "ศาสนสถาน" in h)) or h in ("ชื่อ", "ชื่อมัสยิด"),
    "province": lambda h: "จังหวัด" in h,
    "district": lambda h: "อำเภอ" in h or h.startswith("เขต"),
    "subdistrict": lambda h: "ตำบล" in h or "แขวง" in h,
    "reg_no": lambda h: "ทะเบียน" in h,
    "address": lambda h: "ที่อยู่" in h or "ที่ตั้ง" in h,
    "seq": lambda h: h == "ลำดับ",
    "key": lambda h: h.upper() == "KEY",
}


def _find_header(raw: pd.DataFrame) -> int | None:
    for i in range(min(25, len(raw))):
        cells = [str(c) for c in raw.iloc[i].tolist()]
        if any("จังหวัด" in c for c in cells) and any("ชื่อ" in c or "มัสยิด" in c for c in cells):
            return i
    return None


def read_dra_xlsx(path: Path, overrides: dict[str, str]) -> pd.DataFrame:
    frames = []
    for sheet, raw in pd.read_excel(path, sheet_name=None, header=None, dtype=str).items():
        h = _find_header(raw)
        if h is None:
            print(f"[dra] ข้ามชีต '{sheet}' (หาแถวหัวตารางไม่เจอ)")
            continue
        df = raw.iloc[h + 1:].copy()
        df.columns = [re.sub(r"\s+", "", str(c)) for c in raw.iloc[h]]
        mapping = {}
        for key, rule in COL_RULES.items():
            if key in overrides:
                mapping[key] = overrides[key]
                continue
            hit = next((c for c in df.columns if rule(c)), None)
            if hit:
                mapping[key] = hit
        if "name" not in mapping:
            print(f"[dra] ข้ามชีต '{sheet}' (ไม่พบคอลัมน์ชื่อ: {list(df.columns)}) — ใช้ --col-name")
            continue
        out = pd.DataFrame({k: df[v] for k, v in mapping.items()})
        if "province" not in out:
            out["province"] = sheet  # บางไฟล์แยกชีตตามจังหวัด
        # ตัดแถวสรุปยอด เช่น '<<จำนวนมัสยิดในจังหวัด>>' (KEY = 'สถิติ') ก่อน ffill
        junk = out["name"].fillna("").str.strip().str.match(r"^(<<|รวม(ทั้งสิ้น|ทั้งหมด)?\s*$|$)")
        if "key" in out:
            junk |= out["key"].fillna("").str.contains("สถิติ")
        if junk.any():
            print(f"[dra] ตัดแถวสรุป/แถวว่าง {int(junk.sum())} แถว")
        out = out[~junk]
        # ไฟล์ราชการชอบ merge cell จังหวัด/อำเภอ -> ffill
        for c in ("province", "district"):
            if c in out:
                out[c] = out[c].ffill()
        frames.append(out)
        print(f"[dra] ชีต '{sheet}': {len(out)} แถว, คอลัมน์ {mapping}")
    if not frames:
        sys.exit("อ่าน XLSX ไม่ได้เลย ตรวจชื่อคอลัมน์แล้วใช้ --col-name/--col-province")
    df = pd.concat(frames, ignore_index=True)
    df = df[df["name"].notna() & df["name"].str.strip().ne("")]
    df["province"] = df["province"].map(clean_province)
    if "district" in df:
        df["district"] = df["district"].map(clean_district)
    return df.fillna("").reset_index(drop=True)


# --------------------------------------------------------------------------- step 2: OSM
def fetch_osm(cache: Path, refresh: bool, query: str = OVERPASS_QUERY) -> list[dict]:
    if cache.exists() and not refresh:
        print(f"[osm] ใช้ cache {cache}")
        return json.loads(cache.read_text(encoding="utf-8"))["elements"]
    print("[osm] query Overpass ทั้งประเทศ (อาจใช้ 1-5 นาที)...")
    for attempt in range(5):
        r = requests.post(OVERPASS_URL, data={"data": query},
                          headers={"User-Agent": USER_AGENT}, timeout=1000)
        if r.status_code not in (429, 502, 503, 504):
            break
        wait = 30 * (attempt + 1)
        print(f"[osm] Overpass ไม่ว่าง ({r.status_code}) รอ {wait} วินาทีแล้วลองใหม่...")
        time.sleep(wait)
    r.raise_for_status()
    cache.write_text(r.text, encoding="utf-8")
    return r.json()["elements"]


@dataclass
class OsmPlace:
    osm_id: str
    province: str
    province_en: str
    lat: float
    lng: float
    name: str
    keys: set[tuple[str, bool]] = field(default_factory=set)
    amphoe: set[str] = field(default_factory=set)   # admin_key ของอำเภอ/เขตที่จุดนี้อยู่ (จาก osm_membership.json)
    tambon: set[str] = field(default_factory=set)


def parse_osm(elements: list[dict]) -> dict[str, list[OsmPlace]]:
    """ผลลัพธ์ foreach: element 'area' ของจังหวัด ตามด้วยมัสยิดในจังหวัดนั้น (รวมที่ไม่มีชื่อ: name = '')"""
    by_prov: dict[str, list[OsmPlace]] = {}
    self_prov_en: dict[str, str] = {}
    cur, cur_en = None, ""
    dropped = 0
    for e in elements:
        t = e.get("tags", {})
        if e["type"] == "area":
            cur = clean_province(t.get("name:th") or t.get("name", ""))
            cur_en = t.get("name:en", "")
            self_prov_en[cur] = cur_en
            by_prov.setdefault(cur, [])
            continue
        if cur is None:
            continue
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lng = e.get("lon") or e.get("center", {}).get("lon")
        names = [t[k] for k in ("name:th", "name", "alt_name", "old_name", "official_name") if t.get(k)]
        names = [n for n in names if norm(n) not in CANON_PREFIXES]  # ชื่อแค่ 'มัสยิด'/'Mosque' = ไม่มีชื่อ
        if lat is None:
            continue
        if any(NOT_MOSQUE.search(n) for n in names):
            dropped += 1
            continue
        keys = set().union(*(variants(n) for n in names)) if names else set()
        by_prov[cur].append(OsmPlace(f"{e['type']}/{e['id']}", cur, cur_en, lat, lng, names[0] if names else "", keys))
    parse_osm.province_en = self_prov_en  # type: ignore[attr-defined]
    allp = [o for v in by_prov.values() for o in v]
    print(f"[osm] มัสยิด {len(allp)} แห่ง (มีชื่อ {sum(1 for o in allp if o.name)}) ใน {len(by_prov)} จังหวัด"
          f", ตัดที่ไม่ใช่มัสยิด {dropped}")
    return by_prov


def load_membership(cache: Path, refresh: bool, osm: dict[str, list[OsmPlace]]) -> None:
    """ใส่ชื่ออำเภอ/ตำบลที่มัสยิด OSM แต่ละจุดตั้งอยู่ (point-in-polygon ฝั่ง Overpass)"""
    by_id = {o.osm_id: o for v in osm.values() for o in v}
    level = None
    names: set[str] = set()
    for e in fetch_osm(cache, refresh, MEMBERSHIP_QUERY):
        t = e.get("tags", {})
        if e["type"] == "area":
            level = "amphoe" if t.get("admin_level") == "6" else "tambon"
            names = {admin_key(n) for n in (t.get("name:th"), t.get("name")) if n}
            continue
        o = by_id.get(f"{e['type']}/{e['id']}")
        if o and level:
            getattr(o, level).update(names)
    n = sum(1 for o in by_id.values() if o.amphoe)
    print(f"[osm] รู้อำเภอของมัสยิด OSM {n}/{len(by_id)} แห่ง, รู้ตำบล {sum(1 for o in by_id.values() if o.tambon)}")


# --------------------------------------------------------------------------- step 3: match
def reg_amphoe_key(district: str, province: str) -> str:
    d = admin_key(district)
    return admin_key("เมือง" + province) if d == admin_key("เมือง") else d  # XLSX 'เมือง' = OSM 'อำเภอเมืองกระบี่'


def match_province(regs: pd.DataFrame, osm: list[OsmPlace], known_amphoe: set[str]) -> list[dict]:
    """จับคู่ 1:1 แบบ greedy ตามคะแนนสูงสุดก่อน เฉพาะคู่ที่อยู่อำเภอเดียวกัน"""
    reg_keys, reg_amp = [], []
    for n, prov, dist in zip(regs["name"], regs["province"], regs.get("district", [""] * len(regs))):
        k = variants(n)
        if re.search(r"กลาง(ประจำ)?จังหวัด", n):
            # 'ตักวา มัสยิดกลางประจำจังหวัด' ↔ OSM 'มัสยิดกลางจังหวัดตรัง'
            k |= variants(re.sub(r"\(?มัสยิดกลาง(ประจำ)?จังหวัด\)?", "", n))
            k.add((norm("มัสยิดกลางจังหวัด" + prov), False))
        reg_keys.append(k)
        a = reg_amphoe_key(dist, prov)
        reg_amp.append(a if a in known_amphoe else None)  # ชื่ออำเภอไม่รู้จักใน OSM -> ไม่กรอง

    def same_amphoe(i: int, o: OsmPlace) -> bool:
        return reg_amp[i] is None or not o.amphoe or reg_amp[i] in o.amphoe

    pairs, second = [], {}
    for i, rk in enumerate(reg_keys):
        scored = sorted(((name_score(rk, o.keys), j) for j, o in enumerate(osm)
                         if o.keys and same_amphoe(i, o)), reverse=True)
        if scored:
            second[i] = scored[1][0] if len(scored) > 1 else 0
            # คะแนนเสมอ (เช่น ซอลาฮุดดีน/ซอลาหุดดีน หลัง canon) -> ตัดสินด้วยตัวสะกดจริง
            pairs.extend((s, fuzz.ratio(regs["name"][i], osm[j].name), i, j) for s, j in scored[:5] if s >= MATCH_REVIEW)
    pairs.sort(reverse=True)
    used_r, used_o, result = set(), set(), {}
    for s, _, i, j in pairs:
        if i in used_r or j in used_o:
            continue
        used_r.add(i); used_o.add(j)
        result[i] = (s, osm[j])

    # มัสยิด OSM ไม่มีชื่อ: จับคู่ด้วยตำแหน่งเฉพาะตำบลที่มีมัสยิดจดทะเบียน 1 แห่ง และใน OSM มี 1 จุดพอดี
    tam = [admin_key(x) for x in regs.get("subdistrict", [""] * len(regs))]
    reg_in = Counter((reg_amp[i], tam[i]) for i in range(len(regs)) if reg_amp[i] and tam[i])
    osm_in: dict[tuple[str, str], list[int]] = {}
    for j, o in enumerate(osm):
        for cell in {(a, t) for a in o.amphoe for t in o.tambon}:
            osm_in.setdefault(cell, []).append(j)
    position = set()
    for i in range(len(regs)):
        cell = (reg_amp[i], tam[i])
        js = osm_in.get(cell, [])
        if i in used_r or reg_in.get(cell) != 1 or len(js) != 1:
            continue
        j = js[0]
        if osm[j].name or j in used_o:
            continue
        used_r.add(i); used_o.add(j)
        result[i] = (None, osm[j])
        position.add(i)

    rows = []
    for i, r in enumerate(regs.to_dict("records")):
        rec = {
            "id": r.get("reg_no") or (f"dra-{r['seq']}" if r.get("seq") else None),
            "name": r["name"].strip(),
            "type": detect_type(r["name"]),
            "province": r["province"],
            "district": r.get("district", ""),
            "subdistrict": r.get("subdistrict", ""),
            "address": r.get("address", ""),
            "lat": None, "lng": None,
            "osm_id": None, "osm_name": None, "match_score": None,
            "match_status": "unmatched", "coord_source": None,
        }
        if i in result:
            s, o = result[i]
            rec.update(lat=round(o.lat, 6), lng=round(o.lng, 6), osm_id=o.osm_id, osm_name=o.name or None,
                       match_score=round(s, 1) if s is not None else None, coord_source="osm")
            if i in position:
                rec["match_status"] = "position"    # มัสยิดเดียวในตำบลทั้งสองฝั่ง
            elif s >= MATCH_OK and s - second.get(i, 0) > AMBIGUOUS_GAP:
                rec["match_status"] = "matched"
            elif s >= MATCH_OK:
                rec["match_status"] = "ambiguous"   # มีชื่อคล้ายกันหลายแห่งในจังหวัด เช่น นูรุลอิสลาม
            else:
                rec["match_status"] = "review"
        rows.append(rec)
    return rows


# --------------------------------------------------------------------------- step 4: admin-centre fallback
def admin_key(s: str) -> str:
    s = re.sub(r"^(ตำบล|แขวง|อำเภอ|กิ่งอำเภอ|เขต|ต\.|อ\.)\s*", "", str(s or "").strip())
    return canon(s)  # 'สาธร' (XLSX) = 'เขตสาทร' (OSM)


def parse_admin(elements: list[dict]) -> dict[str, dict]:
    """{จังหวัด: {"amphoe": {key: [(lat,lng)]}, "tambon": {key: [(lat,lng)]}}}"""
    out: dict[str, dict] = {}
    cur = None
    for e in elements:
        t = e.get("tags", {})
        if e["type"] == "area":
            cur = out.setdefault(clean_province(t.get("name:th") or t.get("name", "")),
                                 {"amphoe": {}, "tambon": {}})
            continue
        c = e.get("center")
        if cur is None or not c:
            continue
        level = "amphoe" if t.get("admin_level") == "6" else "tambon"
        for n in {t.get("name:th"), t.get("name")} - {None}:
            cur[level].setdefault(admin_key(n), []).append((c["lat"], c["lon"]))
    print(f"[admin] ศูนย์กลางอำเภอ/ตำบลใน {len(out)} จังหวัด")
    return out


def _nearest(cands: list[tuple[float, float]], ref: tuple[float, float] | None) -> tuple[float, float]:
    if ref is None:
        return cands[0]
    return min(cands, key=lambda p: (p[0] - ref[0]) ** 2 + (p[1] - ref[1]) ** 2)


def admin_fallback(rows: list[dict], admin: dict[str, dict]) -> None:
    for r in rows:
        if r["lat"] is not None:
            continue
        a = admin.get(r["province"])
        if not a:
            continue
        d = admin_key(r["district"])
        amp = a["amphoe"].get(d) or (a["amphoe"].get(admin_key("เมือง" + r["province"])) if d == "เมือง" else None)
        amp_c = amp[0] if amp else None
        tam = a["tambon"].get(admin_key(r["subdistrict"])) if r["subdistrict"] else None
        if tam:
            (lat, lng), src = _nearest(tam, amp_c), "subdistrict_center"
        elif amp_c:
            (lat, lng), src = amp_c, "district_center"
        else:
            pts = [p for v in a["amphoe"].values() for p in v] or [p for v in a["tambon"].values() for p in v]
            if not pts:
                continue
            lat, lng = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            src = "province_center"
        r.update(lat=round(lat, 6), lng=round(lng, 6), coord_source=src)


# --------------------------------------------------------------------------- step 5 (optional): nominatim
def geocode_fallback(rows: list[dict], cache_path: Path, limit: int | None = None) -> None:
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    todo = [r for r in rows if r["lat"] is None][:limit]
    print(f"[geo] Nominatim {len(todo)} รายการ (~{len(todo)//60} นาที)")
    for n, r in enumerate(todo, 1):
        name = r["name"] if norm(r["name"]) != canon(r["name"]) else "มัสยิด" + r["name"]
        q = ", ".join(x for x in (name, r["subdistrict"], r["district"], r["province"], "ประเทศไทย") if x)
        if q not in cache:
            try:
                resp = requests.get(NOMINATIM_URL, params={"q": q, "format": "json", "limit": 1, "countrycodes": "th"},
                                    headers={"User-Agent": USER_AGENT}, timeout=30)
                cache[q] = resp.json()[:1] if resp.ok else []
            except requests.RequestException:
                cache[q] = []
            time.sleep(1.1)  # นโยบาย Nominatim: ไม่เกิน 1 request/วินาที
            if n % 50 == 0:
                cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        hit = cache[q]
        # Nominatim มักคืนหมู่บ้าน/ตำบลแทนตัวมัสยิด ซึ่งไม่ดีกว่าศูนย์กลางตำบล -> รับเฉพาะศาสนสถาน
        if hit and hit[0].get("type") == "place_of_worship":
            r.update(lat=round(float(hit[0]["lat"]), 6), lng=round(float(hit[0]["lon"]), 6),
                     coord_source="nominatim", match_status="geocoded")
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- step 5: export
def slugify(en: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (en or "").lower().replace(" province", "")).strip("-")
    return s or fallback


def export(rows: list[dict], out: Path, prov_en: dict[str, str]) -> None:
    (out / "provinces").mkdir(parents=True, exist_ok=True)
    by_prov: dict[str, list[dict]] = {}
    for r in rows:
        by_prov.setdefault(r["province"], []).append(r)
    index = []
    for i, (prov, items) in enumerate(sorted(by_prov.items()), 1):
        slug = slugify(prov_en.get(prov, ""), f"province-{i:02d}")
        items.sort(key=lambda x: (x["district"], x["name"]))
        (out / "provinces" / f"{slug}.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        index.append({"province": prov, "province_en": prov_en.get(prov, ""), "file": f"provinces/{slug}.json",
                      "count": len(items), "with_coords": sum(1 for x in items if x["lat"] is not None)})
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "all.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    simple = [{k: r[k] for k in ("name", "province", "district", "subdistrict", "lat", "lng", "coord_source")}
              for r in rows]
    (out / "mosques.json").write_text(json.dumps(simple, ensure_ascii=False, indent=1), encoding="utf-8")

    with open(out / "review.csv", "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig ให้ Excel อ่านไทยได้
        cols = ["match_status", "match_score", "province", "district", "name", "osm_name", "osm_id", "lat", "lng", "id"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(r for r in rows if r["match_status"] != "matched")

    stats = pd.Series([r["match_status"] for r in rows]).value_counts()
    print("\n[done] สรุปผลการจับคู่")
    print(stats.to_string())
    print("\nที่มาของพิกัด")
    print(pd.Series([r["coord_source"] or "none" for r in rows]).value_counts().to_string())
    print(f"ไฟล์อยู่ที่ {out.resolve()}")


# --------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", type=Path, help="ไฟล์ XLSX ของกรมการศาสนา (ถ้าไม่ใส่จะดาวน์โหลดผ่าน CKAN API)")
    ap.add_argument("--osm-cache", type=Path, default=Path("osm_mosques.json"))
    ap.add_argument("--refresh-osm", action="store_true", help="query Overpass ใหม่แม้มี cache")
    ap.add_argument("--geocode-fallback", action="store_true", help="หาพิกัดที่เหลือด้วย Nominatim")
    ap.add_argument("--geocode-limit", type=int, help="ใช้ Nominatim แค่ N รายการแรก (ไว้ลองดูคุณภาพ)")
    ap.add_argument("--out", type=Path, default=Path("data"))
    for k in COL_RULES:
        ap.add_argument(f"--col-{k.replace('_', '-')}", dest=f"col_{k}", help=f"ชื่อคอลัมน์ {k} ใน XLSX (ถ้าตรวจอัตโนมัติไม่เจอ)")
    a = ap.parse_args()

    xlsx = a.xlsx or download_dra_xlsx(Path("dra_mosques.xlsx"))
    overrides = {k: getattr(a, f"col_{k}") for k in COL_RULES if getattr(a, f"col_{k}")}
    regs = read_dra_xlsx(xlsx, overrides)
    print(f"[dra] รวม {len(regs)} แห่ง, {regs['province'].nunique()} จังหวัด")

    osm = parse_osm(fetch_osm(a.osm_cache, a.refresh_osm))
    prov_en = getattr(parse_osm, "province_en", {})

    missing = sorted(set(regs["province"]) - set(osm))
    if missing:
        print(f"[warn] ชื่อจังหวัดไม่ตรงกับ OSM: {missing} — เพิ่มใน PROVINCE_ALIASES")

    load_membership(Path("osm_membership.json"), a.refresh_osm, osm)
    admin = parse_admin(fetch_osm(Path("osm_admin.json"), a.refresh_osm, ADMIN_QUERY))

    rows = []
    for prov, grp in regs.groupby("province", sort=True):
        known = set(admin.get(prov, {}).get("amphoe", {})) | {k for o in osm.get(prov, []) for k in o.amphoe}
        rows.extend(match_province(grp.reset_index(drop=True), osm.get(prov, []), known))

    if a.geocode_fallback:
        geocode_fallback(rows, Path("nominatim_cache.json"), a.geocode_limit)

    admin_fallback(rows, admin)

    export(rows, a.out, prov_en)


if __name__ == "__main__":
    main()
