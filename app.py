"""
Evynx Crowd Forecasting API
===========================

Local dev :  python app.py
Production:  gunicorn app:app --bind 0.0.0.0:$PORT

Endpoints
  GET /                                    service info
  GET /api/health
  GET /api/recommend?package_id=..&date=YYYY-MM-DD      <- main endpoint
  GET /api/forecast?package_id=..&date=YYYY-MM-DD
  GET /api/alternate_dates?package_id=..&date=..&top=3
  GET /api/alternate_packages?package_id=..&date=..&top=3
  GET /api/package/<package_id>
  GET /api/packages?region=..&group_type=..&limit=50
  GET /api/stats
"""

import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template

try:
    from flask_cors import CORS
    _CORS = True
except ImportError:
    _CORS = False

from crowd_engine import Engine

app = Flask(__name__)
app.json.sort_keys = False
try:                      # emit valid JSON even if a NaN slips into the data
    app.json.allow_nan = False
except Exception:
    pass
if _CORS:
    CORS(app)                      # allow the Evynx site to call this API

ENGINE = Engine()                  # loaded once at boot, ~600 KB of JSON


# ------------------------------------------------------------------ utils --
def _args(require_date=True):
    pid = request.args.get('package_id')
    d = request.args.get('date')
    if not pid:
        return None, None, (jsonify({'error': 'package_id is required'}), 400)
    if require_date:
        if not d:
            return None, None, (jsonify(
                {'error': 'date is required (YYYY-MM-DD)'}), 400)
        try:
            datetime.strptime(d, '%Y-%m-%d')
        except ValueError:
            return None, None, (jsonify(
                {'error': 'date must be YYYY-MM-DD'}), 400)
    if not ENGINE._tour(pid):
        return None, None, (jsonify({'error': f'package {pid} not found'}), 404)
    return pid, d, None


# ------------------------------------------------------------------ routes -
@app.route('/')
def home():
    """Demo page. The template loads all of its data from the API endpoints
    below, so no template variables are needed."""
    return render_template('index.html')


@app.route('/api')
def root():
    s = ENGINE.stats()
    return jsonify({
        'service': 'Evynx Crowd Forecasting API',
        'status': 'ok',
        'places': s['places'],
        'places_measured': s['places_measured'],
        'tours': s['tours'],
        'swappable_tours': s['swappable_tours'],
        'endpoints': [
            '/api/health',
            '/api/recommend?package_id=..&date=YYYY-MM-DD',
            '/api/forecast?package_id=..&date=YYYY-MM-DD',
            '/api/alternate_dates?package_id=..&date=..',
            '/api/alternate_packages?package_id=..&date=..',
            '/api/package/<package_id>',
            '/api/packages',
            '/api/stats',
        ],
    })


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', **ENGINE.stats()})


@app.route('/api/recommend')
def recommend():
    pid, d, err = _args()
    if err:
        return err
    return jsonify(ENGINE.recommend(pid, d))


@app.route('/api/forecast')
def forecast():
    pid, d, err = _args()
    if err:
        return err
    return jsonify(ENGINE.forecast(pid, d))


@app.route('/api/alternate_dates')
def alt_dates():
    pid, d, err = _args()
    if err:
        return err
    top = min(int(request.args.get('top', 3)), 10)
    return jsonify({'package_id': pid, 'from_date': d,
                    'alternatives': ENGINE.alternate_dates(pid, d, top=top)})


@app.route('/api/alternate_packages')
def alt_pkgs():
    pid, d, err = _args()
    if err:
        return err
    top = min(int(request.args.get('top', 3)), 10)
    alts, why = ENGINE.alternate_packages(pid, d, top=top)
    return jsonify({'package_id': pid, 'date': d,
                    'alternatives': alts or [], 'note': why})


@app.route('/api/package/<path:package_id>')
def package(package_id):
    t = ENGINE._tour(package_id)
    if not t:
        return jsonify({'error': f'package {package_id} not found'}), 404
    sw = ENGINE.swappable()
    return jsonify({
        'package_id': t['package_id'], 'title': t['title'],
        'region': t['region'], 'group_type': t['group_type'],
        'duration': t['duration'], 'route': t['route'],
        'intent': t['_intent'],
        'swappable': str(t['package_id']) in sw,
        'measurement_class': sw.get(str(t['package_id'])),
        'stops': t['stops'],
    })


@app.route('/api/packages')
def packages():
    region = request.args.get('region')
    gt = request.args.get('group_type')
    limit = min(int(request.args.get('limit', 50)), 1000)
    sw = ENGINE.swappable()
    out = []
    for pid, t in ENGINE.tours.items():
        if region and t['region'] != region:
            continue
        if gt and t['group_type'] != gt:
            continue
        out.append({'package_id': t['package_id'], 'title': t['title'],
                    'region': t['region'], 'group_type': t['group_type'],
                    'duration': t['duration'],
                    'swappable': pid in sw})
        if len(out) >= limit:
            break
    return jsonify({'count': len(out), 'packages': out})


@app.route('/api/year_curve')
def year_curve():
    pid, _, err = _args(require_date=False)
    if err:
        return err
    year = int(request.args.get('year', 2026))
    return jsonify({'package_id': pid, 'year': year,
                    'curve': ENGINE.year_curve(pid, year)})


@app.route('/api/stats')
def stats():
    return jsonify(ENGINE.stats())


@app.errorhandler(404)
def nf(e):
    return jsonify({'error': 'endpoint not found', 'see': '/'}), 404


@app.errorhandler(500)
def se(e):
    return jsonify({'error': 'internal server error'}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)