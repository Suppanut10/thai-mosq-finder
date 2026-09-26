# Mosque Finder TH

Static web app for Muslim travellers to find registered mosques/สุเหร่า in Thailand. No backend; deployed free on GitHub Pages.

## Goals
1. Pick a province → list + map
2. "ใกล้ฉัน" (near me) → sort by distance (geolocation → nearest province + neighbours)
3. Navigate button → Google Maps (coords if known, else search by name + ตำบล + อำเภอ)
4. Mobile-first (test at 375px)
5. Deploy to GitHub Pages via GitHub Actions

## Data sources
- `ms_3028_04-001.xlsx` — กรมการศาสนา registered mosques, ปี 2565 (4,052 rows; name, ตำบล, อำเภอ, จังหวัด; **no coordinates**)
- OpenStreetMap via Overpass — mosque points (`osm_mosques.json`) and district/subdistrict centres (`osm_admin.json`), both cached
- Footer must credit กรมการศาสนา ปี 2565 and © OpenStreetMap contributors (ODbL)

## Structure
```
build_mosque_data.py     XLSX + OSM → data/ (name matching, admin-centre fallback)
data/                    generated — index.json, provinces/<slug>.json, all.json, mosques.json, review.csv
web/                     Vite + vanilla JS + Leaflet
  public/data/           copied from data/ by `npm run data` (gitignored)
  tests/                 Playwright tests (planned, step 5)
.github/workflows/deploy.yml   push to main → build web/ → publish web/dist to GitHub Pages
README.md                user-facing docs (Thai), incl. yearly data update procedure
```

## Data pipeline
1. Read XLSX, drop summary rows (`KEY` = สถิติ, `<<...>>`)
2. Match names with OSM mosques per province, only within the same อำเภอ (`osm_membership.json`, point-in-polygon from Overpass; slow query ~11 min, cached). rapidfuzz; `MATCH_OK=85`, `MATCH_REVIEW=70`, `AMBIGUOUS_GAP=3`. Do not lower thresholds to gain matches. Names go through `canon()` (ห์/ฮ์, ย/ญ, สระยาว/สั้น, ะ, ตัวซ้ำ); village names in parentheses alone never match; direction suffixes (ออก/ตก/...) must agree.
3. Unnamed OSM mosque ↔ registered mosque when both are the only one in their ตำบล → `match_status: position`
4. No match → centre of ตำบล → อำเภอ → จังหวัด (`coord_source` records which)
5. `--geocode-fallback [--geocode-limit N]` uses Nominatim — tested on 50 rows: 0 useful hits (it searches the same OSM data), not worth a full run

`coord_source`: `osm` | `nominatim` | `subdistrict_center` | `district_center` | `province_center`. Only `osm`/`nominatim` are real mosque locations; the web app should treat the centres as approximate (navigate by name search instead).

## Commands
```sh
python3 -m venv .venv && source .venv/bin/activate
pip install pandas openpyxl requests rapidfuzz
python build_mosque_data.py --xlsx ms_3028_04-001.xlsx              # uses cached OSM
python build_mosque_data.py --xlsx ms_3028_04-001.xlsx --refresh-osm
python build_mosque_data.py --xlsx ms_3028_04-001.xlsx --geocode-fallback
```
Web:
```sh
cd web
npm install
npm run data      # copy ../data -> public/data (+ province centres in index.json)
npm run dev       # runs data first; http://localhost:5173
npm run build     # -> web/dist
```
Web source: `src/main.js` (UI/state), `src/data.js` (lazy province loading, nearby provinces), `src/map.js` (Leaflet; exact = solid dots, approximate = grouped dashed circles), `src/geo.js` (distance, Google Maps links).

## Conventions
- USER_AGENT has no email (user's choice); Overpass returns 406 for the placeholder email.
- Province JSON should stay ≤ 200KB — strip fields the web doesn't use.
- Code comments in Thai, matching `build_mosque_data.py`.
