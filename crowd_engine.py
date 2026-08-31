"""
================================================================================
 EVYNX CROWD FORECASTING ENGINE  —  FINAL MODEL
================================================================================

 WHAT IT DOES
   Given a package ID and a departure date, returns:
     1. how crowded that package will be, with reasons
     2. a recommendation — either a quieter PACKAGE or a quieter DATE

 THE TWO-TRACK DESIGN
   Package swap needs both packages measured and in the same measurement class.
   That holds for 275 of 632 packages. For the rest we fall back to a date
   suggestion, which works for all 632 because it only needs the seasonal
   model (validated 92.8%).

     package swap possible  -> offer quieter package (+ date as secondary)
     package swap not possible -> offer quieter date

 THREE INDICES  (never mixed)
   seasonal_index        Layers 1-3, month level
   recommendation_index  seasonal + verified festival   <- ALL ranking uses this
   display_index         recommendation + weekend/holiday  <- shown to user

 KEY RULES ENFORCED
   * comparisons only within the same measurement class
   * ESTIMATE-class places never drive a recommendation
   * per-night dates, not departure date, for festivals and season gates
   * Best Seasons gate applied per stop before ranking
   * group tours never receive an arbitrary-date suggestion

 FILES REQUIRED (same folder)
   places.json  seasonal.json  tours.json  festivals.json  holidays.json

 USAGE
   from crowd_engine import Engine
   e = Engine()
   e.forecast('TP931VVRNR', '2026-11-08')
   e.recommend('TP931VVRNR', '2026-11-08')
================================================================================
"""

import json, os, calendar
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- constants --
FESTIVAL_FLOOR   = 80     # a festival crowds a place regardless of its usual level
FESTIVAL_ADD     = 35     # ...and adds on top for already-busy places
WEEKEND_MULT     = 1.08   # a busy place stays busy midweek, so only a nudge
HOLIDAY_MULT     = 1.10
NATURE_FEST_SENS = 0.35   # festivals fill temples, not beaches

BANDS = [(30, 'Quiet'), (55, 'Moderate'), (75, 'Busy'), (101, 'Very Busy')]

# a swap is only offered if the alternative is meaningfully quieter
SWAP_MARGIN      = 8.0
DATE_MARGIN      = 5.0
HIGH_THRESHOLD   = 65.0   # below this we do not push an alternative at all

# intent bands — crowd-expected packages get logistics advice, not a swap
CROWD_EXPECTED = {'pilgrimage', 'religious', 'temple', 'spiritual', 'yatra',
                  'char dham', 'jyotirlinga', 'sacred'}
CROWD_AVERSE   = {'trek', 'wildlife', 'safari', 'offbeat', 'hidden', 'retreat',
                  'workation', 'solitude', 'camping'}

MONTH_NAME = {i: calendar.month_name[i] for i in range(1, 13)}


def _band(v):
    for hi, lab in BANDS:
        if v < hi:
            return lab
    return 'Very Busy'


def _load(fn):
    with open(os.path.join(HERE, fn)) as f:
        return json.load(f)


# ============================================================== ENGINE =======
class Engine:

    def __init__(self):
        self.places = {p['key']: p for p in _load('places.json')}
        s = _load('seasonal.json')
        self.city_curve   = s['city']
        self.state_curve  = s['state']
        self.region_curve = s['region']
        self.tours = {str(t['package_id']): t for t in _load('tours.json')}
        self.by_id = {str(t['id']): t for t in _load('tours.json')}
        self.festivals = _load('festivals.json')
        self.holidays = _load('holidays.json')
        for t in self.tours.values():
            t['_intent'] = self._intent(t)
        self._swappable = None

    # ---------------------------------------------------------- helpers ----
    def _tour(self, pid):
        return self.tours.get(str(pid)) or self.by_id.get(str(pid))

    @staticmethod
    def _intent(t):
        txt = f"{t.get('title','')} {t.get('slug','')}".lower()
        if any(w in txt for w in CROWD_EXPECTED):
            return 'crowd_expected'
        if any(w in txt for w in CROWD_AVERSE):
            return 'crowd_averse'
        return 'neutral'

    def _seasonal(self, key, month):
        """City -> state -> region fallback. Returns (score, tier)."""
        p = self.places.get(key)
        if p:
            c = str(p['city']).strip().lower()
            if c in self.city_curve:
                return self.city_curve[c].get(str(month)), 'city'
            if key in self.city_curve:
                return self.city_curve[key].get(str(month)), 'city'
            st = str(p['state']).strip().lower()
            if st in self.state_curve:
                return self.state_curve[st].get(str(month)), 'state'
            rg = str(p['region']).strip().lower()
            if rg in self.region_curve:
                return self.region_curve[rg].get(str(month)), 'region'
        if key in self.city_curve:
            return self.city_curve[key].get(str(month)), 'city'
        return None, 'none'

    def _festivals_on(self, key, d):
        """Verified festival windows covering this place on this date."""
        p = self.places.get(key)
        cl = key if not p else str(p['city']).lower()
        sl = '' if not p else str(p['state']).lower()
        nl = key
        hits = []
        for f in self.festivals:
            v = f['value']
            hit = ((f['scope'] == 'city' and (v == nl or v == cl)) or
                   (f['scope'] == 'state' and v == sl))
            if hit and f['start'] <= d <= f['end']:
                hits.append(f)
        return hits

    def _is_nature(self, key):
        p = self.places.get(key)
        if not p:
            return False
        txt = f"{p['name']} {p.get('cls','')}".lower()
        return any(w in txt for w in
                   ('beach', 'park', 'lake', 'falls', 'valley', 'island',
                    'sanctuary', 'wildlife', 'hills', 'trek'))

    # ------------------------------------------------------ stop scoring ---
    def _score_stop(self, key, d):
        """One stop on one calendar date. Returns the three indices."""
        dt = datetime.strptime(d, '%Y-%m-%d').date()
        seasonal, tier = self._seasonal(key, dt.month)
        if seasonal is None:
            return None

        rec = seasonal
        reasons = []

        fests = self._festivals_on(key, d)
        if fests:
            f = max(fests, key=lambda x: x['magnitude'])
            sens = NATURE_FEST_SENS if self._is_nature(key) else 1.0
            boosted = min(100.0, max(seasonal + FESTIVAL_ADD * sens,
                                     FESTIVAL_FLOOR * sens))
            rec = max(rec, boosted)
            reasons.append(f"{f['name']} in {self.places.get(key,{}).get('name',key)}")

        disp = rec
        if dt.weekday() >= 5:
            disp *= WEEKEND_MULT
            reasons.append(f"{dt.strftime('%A')} — weekend")
        hol = self.holidays.get(d)
        if hol:
            disp *= HOLIDAY_MULT
            reasons.append(f"Public holiday — {hol}")
        disp = min(100.0, disp)

        p = self.places.get(key, {})
        in_season = dt.month in (p.get('season_months') or list(range(1, 13)))

        return {
            'key': key,
            'name': p.get('name', key.title()),
            'date': d,
            'seasonal_index': round(seasonal, 1),
            'recommendation_index': round(rec, 1),
            'display_index': round(disp, 1),
            'tier': tier,
            'in_season': in_season,
            'class': p.get('cls', 'UNKNOWN'),
            'reasons': reasons,
        }

    # ------------------------------------------------------- FORECAST ------
    def forecast(self, pid, dep):
        """Crowd forecast for a package on a departure date."""
        t = self._tour(pid)
        if not t:
            return {'error': f'package {pid} not found'}

        d0 = datetime.strptime(dep, '%Y-%m-%d').date()
        stops, cursor = [], 0
        for s in t['stops']:
            sd = (d0 + timedelta(days=cursor)).isoformat()
            r = self._score_stop(s['key'], sd)
            cursor += s['days']
            if r:
                r['days'] = s['days']
                r['raw'] = s['raw']
                stops.append(r)

        if not stops:
            return {'package_id': t['package_id'], 'title': t['title'],
                    'region': t['region'], 'group_type': t['group_type'],
                    'departure_date': dep, 'error': 'no_crowd_data',
                    'message': ('Crowd information is not yet available for '
                                'this route.')}

        tot = sum(s['days'] for s in stops)
        wm = lambda f: round(sum(s[f] * s['days'] for s in stops) / tot, 1)

        peak = sorted(stops, key=lambda s: (-s['recommendation_index'],
                                            -s['days'],
                                            {'city': 0, 'state': 1, 'region': 2}
                                            .get(s['tier'], 3)))[0]

        reasons = []
        for s in stops:
            for r in s['reasons']:
                if r not in reasons:
                    reasons.append(r)
        if not reasons:
            sm = MONTH_NAME[d0.month]
            lv = ('peak' if wm('seasonal_index') > 60
                  else 'off' if wm('seasonal_index') < 30 else 'shoulder')
            reasons.append(f'{sm} — {lv} season on this route')

        out_of_season = [s['name'] for s in stops if not s['in_season']]
        tiers = [s['tier'] for s in stops]

        return {
            'package_id': t['package_id'],
            'title': t['title'],
            'region': t['region'],
            'group_type': t['group_type'],
            'departure_date': dep,
            'duration': t['duration'],
            'seasonal_index': wm('seasonal_index'),
            'recommendation_index': wm('recommendation_index'),
            'display_index': wm('display_index'),
            'band': _band(wm('display_index')),
            'decision_band': _band(wm('recommendation_index')),
            'peak_stop': {
                'name': peak['name'], 'date': peak['date'],
                'index': peak['recommendation_index'],
                'display_index': peak['display_index'],
                'days': peak['days'], 'tier': peak['tier'],
                # nameable at city tier, or when a date-verified festival
                # names this specific stop
                'nameable': (peak['tier'] == 'city'
                             or bool(self._festivals_on(peak['key'],
                                                        peak['date']))),
            },
            'reasons': reasons,
            'coverage': {
                'stops': len(stops),
                'city_tier': tiers.count('city'),
                'state_tier': tiers.count('state'),
                'region_tier': tiers.count('region'),
                'in_season': sum(1 for s in stops if s['in_season']),
            },
            'out_of_season_stops': out_of_season,
            'confidence': ('high' if all(x == 'city' for x in tiers)
                           else 'low' if 'region' in tiers else 'medium'),
            'stops': stops,
        }

    # -------------------------------------------------- swap eligibility ---
    def _package_class(self, t):
        """A package is swappable only if EVERY stop is measured and in one class."""
        cls = set()
        for s in t['stops']:
            p = self.places.get(s['key'])
            if not p or p['cls'] == 'ESTIMATE':
                return None
            cls.add(p['cls'])
        return cls.pop() if len(cls) == 1 else None

    def swappable(self):
        if self._swappable is None:
            self._swappable = {}
            for pid, t in self.tours.items():
                c = self._package_class(t)
                if c:
                    self._swappable[pid] = c
        return self._swappable

    # ------------------------------------------------- alternate package ---
    def alternate_packages(self, pid, dep, top=3):
        t = self._tour(pid)
        sw = self.swappable()
        my_cls = sw.get(str(t['package_id']))
        if not my_cls:
            return None, 'package has unmeasured stops — not comparable'

        base = self.forecast(pid, dep)
        cands = []
        for other_id, cls in sw.items():
            if other_id == str(t['package_id']):
                continue
            o = self.tours[other_id]
            if o['region'] != t['region']:
                continue                      # never compare across regions
            if cls != my_cls:
                continue                      # never compare across classes
            if o['_intent'] != t['_intent']:
                continue
            f = self.forecast(other_id, dep)
            if 'error' in f:
                continue
            if f['recommendation_index'] < base['recommendation_index'] - SWAP_MARGIN:
                cands.append(f)
        cands.sort(key=lambda x: x['recommendation_index'])
        if not cands:
            return [], 'no quieter comparable package in this region'
        return cands[:top], None

    # ---------------------------------------------------- alternate date ---
    def alternate_dates(self, pid, dep, horizon=180, top=3):
        t = self._tour(pid)
        base = self.forecast(pid, dep)
        d0 = datetime.strptime(dep, '%Y-%m-%d').date()

        seen, cands = set(), []
        for off in range(-horizon, horizon + 1, 7):
            nd = d0 + timedelta(days=off)
            if nd <= date.today() or nd.isoformat() == dep:
                continue
            f = self.forecast(pid, nd.isoformat())
            if 'error' in f:
                continue
            if f['out_of_season_stops']:        # hard gate, per stop
                continue
            if f['recommendation_index'] < base['recommendation_index'] - DATE_MARGIN:
                kk = (nd.year, nd.month)
                if kk in seen:
                    continue
                seen.add(kk)
                cands.append(f)
        # quietest first, but prefer nearer dates when scores are close
        def rank(x):
            gap = abs((datetime.strptime(x['departure_date'], '%Y-%m-%d').date()
                       - d0).days)
            return (round(x['recommendation_index'] / 5), gap)
        cands.sort(key=rank)
        return cands[:top]

    # -------------------------------------------------------- RECOMMEND ---
    def recommend(self, pid, dep):
        """Main entry point. Always returns actionable output."""
        base = self.forecast(pid, dep)
        if 'error' in base:
            base['recommendation_type'] = 'unavailable'
            base['alternatives'] = []
            return base

        t = self._tour(pid)
        intent = t['_intent']
        idx = base['recommendation_index']

        res = {
            'forecast': {kk: base[kk] for kk in
                         ('package_id', 'title', 'region', 'group_type',
                          'departure_date', 'display_index', 'band',
                          'decision_band', 'peak_stop', 'reasons',
                          'confidence', 'coverage')},
            'intent': intent,
            'recommendation_type': None,
            'message': None,
            'alternatives': [],
        }

        # out-of-season is a hard warning regardless of crowd level
        if base['out_of_season_stops']:
            res['warning'] = ('Outside recommended season: '
                              + ', '.join(base['out_of_season_stops']))

        # not busy enough to act on
        if idx < HIGH_THRESHOLD:
            res['recommendation_type'] = 'none'
            if base['decision_band'] in ('Busy', 'Very Busy'):
                res['message'] = (
                    f"Moderately busy on {dep}, but this is already one of the "
                    "better times for this route.")
            else:
                res['message'] = (f"This trip looks {base['band'].lower()} on "
                                  f"{dep}. No change needed.")
            return res

        # crowd-expected intents: advise, do not send them away
        if intent == 'crowd_expected':
            res['recommendation_type'] = 'logistics'
            pk = base['peak_stop']
            where = pk['name'] if pk['nameable'] else 'the main stop'
            res['message'] = (
                f"Expect heavy crowds, especially at {where}. "
                "This is peak pilgrimage season — book darshan slots and "
                "accommodation at least 30 days ahead.")
            return res

        # try a package swap first
        alts, why = self.alternate_packages(pid, dep)
        if alts:
            res['recommendation_type'] = 'alternate_package'
            res['message'] = (f"This trip is {base['band'].lower()} on {dep}. "
                              f"{len(alts)} quieter option"
                              f"{'s' if len(alts) > 1 else ''} in the same region.")
            res['alternatives'] = [{
                'package_id': a['package_id'], 'title': a['title'],
                'display_index': a['display_index'], 'band': a['band'],
                'duration': a.get('duration'),
                'quieter_by': round(base['recommendation_index']
                                    - a['recommendation_index'], 1),
            } for a in alts]
            return res

        # fall back to a date
        if t['group_type'] == 'Group':
            res['recommendation_type'] = 'group_departure'
            res['message'] = ("This is a fixed-departure group tour, so the date "
                              "cannot be moved freely. Ask the operator for the "
                              "next scheduled departure.")
            res['note'] = why
            return res

        dates = self.alternate_dates(pid, dep)
        if dates:
            res['recommendation_type'] = 'alternate_date'
            res['message'] = (f"This trip is {base['band'].lower()} on {dep}. "
                              "These dates are quieter for the same package.")
            res['alternatives'] = [{
                'date': d['departure_date'],
                'display_index': d['display_index'], 'band': d['band'],
                'quieter_by': round(base['recommendation_index']
                                    - d['recommendation_index'], 1),
                'reasons': d['reasons'][:2],
            } for d in dates]
            res['note'] = why
            return res

        res['recommendation_type'] = 'none_available'
        res['message'] = (f"{dep} is already among the quieter options for this "
                          "route. No better date or comparable package found.")
        res['note'] = why
        return res

    # -------------------------------------------------------- year curve ---
    def year_curve(self, pid, year=None, day=15):
        """Monthly recommendation index for one package across a year."""
        t = self._tour(pid)
        if not t:
            return []
        year = year or date.today().year
        out = []
        for m in range(1, 13):
            d = date(year, m, day).isoformat()
            f = self.forecast(pid, d)
            if 'error' in f:
                out.append({'month': m, 'label': MONTH_NAME[m][:3],
                            'index': None, 'band': None, 'in_season': None})
                continue
            out.append({
                'month': m,
                'label': MONTH_NAME[m][:3],
                'index': f['recommendation_index'],
                'band': _band(f['recommendation_index']),
                'in_season': not f['out_of_season_stops'],
            })
        return out

    # ------------------------------------------------------------ stats ----
    def stats(self):
        sw = self.swappable()
        from collections import Counter
        return {
            'places': len(self.places),
            'places_measured': sum(1 for p in self.places.values()
                                   if p['cls'] != 'ESTIMATE'),
            'tours': len(self.tours),
            'swappable_tours': len(sw),
            'swappable_by_class': dict(Counter(sw.values())),
            'swappable_by_region': dict(Counter(
                self.tours[k]['region'] for k in sw)),
        }


if __name__ == '__main__':
    import pprint
    e = Engine()
    print('=' * 74)
    pprint.pprint(e.stats())
    print('=' * 74)
