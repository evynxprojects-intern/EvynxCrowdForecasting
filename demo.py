"""Worked examples covering every recommendation path."""
from crowd_engine import Engine
e = Engine()

def show(pid, d):
    r = e.recommend(pid, d)
    f = r.get('forecast', r)
    print('=' * 74)
    print(f"  {f.get('title','?')[:64]}")
    print(f"  {d}  |  {f.get('region','')}  |  {f.get('group_type','')}")
    print('-' * 74)
    if r['recommendation_type'] == 'unavailable':
        print('  ', r.get('message')); print(); return
    print(f"  Crowd  : {f['display_index']}  ({f['band']})   confidence: {f['confidence']}")
    ps = f['peak_stop']
    where = ps['name'] if ps['nameable'] else 'one stop on this route'
    print(f"  Busiest: {where} — {ps['index']} on {ps['date']} ({ps['days']}d)")
    print(f"  Why    : " + '; '.join(f['reasons'][:3]))
    if r.get('warning'): print(f"  WARNING: {r['warning']}")
    print(f"  ACTION [{r['recommendation_type']}]")
    print(f"  {r['message']}")
    for a in r['alternatives']:
        if 'date' in a:
            print(f"     -> {a['date']}   {a['display_index']} ({a['band']})"
                  f"   {a['quieter_by']} points quieter")
        else:
            print(f"     -> {a['title'][:52]}")
            print(f"        {a['display_index']} ({a['band']})  "
                  f"{a['quieter_by']} points quieter  {a.get('duration','')}")
    print()

def find(sub):
    for pid, t in e.tours.items():
        if sub.lower() in t['title'].lower(): return pid

print('\nEVYNX CROWD ENGINE — WORKED EXAMPLES\n')
show(find('Kutch Desert Drive'), '2026-11-08')   # festival + group
show(find('Wayanad Scenic Hill'), '2026-11-08')  # package swap
show(find('Vizag Coastal'), '2026-11-08')        # date swap
show(find('Ashtavinayak'), '2026-11-08')         # pilgrimage logistics
show(find('Mysore'), '2026-06-15')               # quiet, no action

print('=' * 74)
s = e.stats()
print(f"  places {s['places']} ({s['places_measured']} measured)   "
      f"tours {s['tours']} ({s['swappable_tours']} swappable)")
print('=' * 74)
