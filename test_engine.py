"""Regression tests — every assertion traces to a finding in the project."""
from crowd_engine import Engine
from datetime import datetime, timedelta
import sys

e = Engine()
P, F = 0, 0
def check(name, cond, detail=''):
    global P, F
    if cond: P += 1; print(f'  PASS  {name}')
    else:    F += 1; print(f'  FAIL  {name}   {detail}')

def find(sub):
    for pid, t in e.tours.items():
        if sub.lower() in t['title'].lower(): return pid
    return None

print('='*72); print('  REGRESSION TESTS'); print('='*72)

# --- 1. festival detection is date-specific, not month-specific -------------
kutch = find('Kutch Desert Drive')
a = e.forecast(kutch, '2026-11-08')      # inside Rann Utsav
b = e.forecast(kutch, '2026-09-20')      # outside it
check('Rann Utsav fires for Dhordo in November',
      any('Rann Utsav' in r for r in a['reasons']))
check('Rann Utsav does NOT fire in September',
      not any('Rann Utsav' in r for r in b['reasons']))
check('festival raises the index', a['recommendation_index'] > b['recommendation_index'])

# --- 2. per-night dates, not departure date --------------------------------
t = e.tours[kutch]
f = e.forecast(kutch, '2026-11-08')
dates = [s['date'] for s in f['stops']]
check('each stop gets its own calendar date', len(set(dates)) == len(dates),
      str(dates))

# --- 3. weekend/holiday affect display only, never the decision -------------
sat, wed = None, None
for off in range(0, 14):
    d = (datetime(2026,9,1) + timedelta(days=off)).date()
    if d.weekday() == 5 and not sat: sat = d.isoformat()
    if d.weekday() == 2 and not wed: wed = d.isoformat()
pid = find('Mysore')
fs, fw = e.forecast(pid, sat), e.forecast(pid, wed)
check('weekend raises display_index', fs['display_index'] > fw['display_index'])
check('weekend does NOT change recommendation_index',
      abs(fs['recommendation_index'] - fw['recommendation_index']) < 0.05)

# --- 4. swaps never cross region or class ----------------------------------
bad_region = bad_class = 0
sw = e.swappable()
for pid in list(sw)[:120]:
    alts, _ = e.alternate_packages(pid, '2026-11-08')
    if not alts: continue
    src = e.tours[pid]
    for a in alts:
        o = e.tours[str(a['package_id'])]
        if o['region'] != src['region']: bad_region += 1
        if sw.get(str(a['package_id'])) != sw[pid]: bad_class += 1
check('no cross-region swaps', bad_region == 0, f'{bad_region} found')
check('no cross-class swaps', bad_class == 0, f'{bad_class} found')

# --- 5. ESTIMATE places never make a package swappable ---------------------
leak = 0
for pid in sw:
    for s in e.tours[pid]['stops']:
        p = e.places.get(s['key'])
        if not p or p['cls'] == 'ESTIMATE': leak += 1
check('no ESTIMATE stop inside a swappable package', leak == 0, f'{leak} leaks')

# --- 6. group tours never get an arbitrary-date suggestion -----------------
bad = 0
for pid, t in e.tours.items():
    if t['group_type'] != 'Group': continue
    r = e.recommend(pid, '2026-11-08')
    if r['recommendation_type'] == 'alternate_date': bad += 1
check('group tours never offered a free date', bad == 0, f'{bad} found')

# --- 7. Best Seasons hard gate on alternate dates ---------------------------
viol = 0
for pid in list(e.tours)[:200]:
    for alt in e.alternate_dates(pid, '2026-11-08', top=3):
        if alt['out_of_season_stops']: viol += 1
check('alternate dates never out of season', viol == 0, f'{viol} violations')

# --- 8. every package returns something actionable -------------------------
missing = 0
for pid in e.tours:
    r = e.recommend(pid, '2026-11-08')
    if not r.get('message'): missing += 1
check('every package returns a message', missing == 0, f'{missing} empty')

# --- 9. pilgrimage gets logistics, never "switch package" ------------------
bad = 0
for pid, t in e.tours.items():
    r = e.recommend(pid, '2026-11-08')
    if r.get('intent') == 'crowd_expected' and \
       r['recommendation_type'] == 'alternate_package': bad += 1
check('pilgrimage never told to switch package', bad == 0, f'{bad} found')

# --- 10. peak named only when city-tier OR festival-verified --------------
bad = 0
for pid in list(e.tours)[:250]:
    f = e.forecast(pid, '2026-11-08')
    if 'error' in f: continue
    ps = f['peak_stop']
    if not ps['nameable']:
        continue
    key = next((s['key'] for s in f['stops'] if s['name'] == ps['name']), None)
    justified = ps['tier'] == 'city' or bool(e._festivals_on(key, ps['date']))
    if not justified: bad += 1
check('peak named only at city tier or festival-verified', bad == 0, f'{bad} found')

# --- 11. indices ordered correctly ----------------------------------------
bad = 0
for pid in list(e.tours)[:250]:
    f = e.forecast(pid, '2026-11-08')
    if 'error' in f: continue
    if not (f['seasonal_index'] <= f['recommendation_index'] + 0.05 <=
            f['display_index'] + 0.1): bad += 1
check('seasonal <= recommendation <= display', bad == 0, f'{bad} violations')

# --- 12. scores stay in range --------------------------------------------
bad = 0
for pid in e.tours:
    f = e.forecast(pid, '2026-11-08')
    if 'error' in f: continue
    for k in ('seasonal_index','recommendation_index','display_index'):
        if not (0 <= f[k] <= 100): bad += 1
check('all indices within 0-100', bad == 0, f'{bad} out of range')

# --- 13. determinism ------------------------------------------------------
r1 = e.recommend(find('Wayanad'), '2026-11-08')
r2 = Engine().recommend(find('Wayanad'), '2026-11-08')
check('deterministic across instances', r1 == r2)

print('='*72)
print(f'  {P} passed, {F} failed')
print('='*72)
sys.exit(1 if F else 0)
