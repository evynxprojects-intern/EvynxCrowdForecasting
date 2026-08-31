# Deploying to Render

The engine is fully self-contained — all data is local JSON (~600 KB).
No Google Drive, no gdown, no model pickle. Cold start is a few seconds.

---

## 1. Push to GitHub

Create a new repository, then from the `final_model` folder:

```bash
git init
git add .
git commit -m "Evynx crowd forecasting engine"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

---

## 2. Create the Render service

1. render.com → **New** → **Web Service**
2. Connect the repository
3. Settings:

| Field | Value |
|---|---|
| Environment | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120` |
| Instance type | Free is fine |

Render also reads the `Procfile`, so the start command may auto-fill.

4. **Create Web Service**

---

## 3. Verify

Open your service URL. You should see JSON:

```json
{ "service": "Evynx Crowd Forecasting API", "status": "ok",
  "places": 617, "tours": 632, "swappable_tours": 290 }
```

Then test the main endpoint:

```
https://<your-service>.onrender.com/api/recommend?package_id=TP931VVRNR&date=2026-11-08
```

---

## 4. Call it from the website

```javascript
const res = await fetch(
  `https://<your-service>.onrender.com/api/recommend` +
  `?package_id=${packageId}&date=${date}`
);
const data = await res.json();

// data.forecast.display_index   number 0-100
// data.forecast.band            Quiet | Moderate | Busy | Very Busy
// data.forecast.reasons         array of strings
// data.recommendation_type      none | alternate_package | alternate_date |
//                               logistics | group_departure | none_available
// data.message                  ready-to-display sentence
// data.alternatives             array
```

CORS is enabled, so browser calls work directly.

---

## Notes

**Free tier sleeps after 15 minutes idle.** First request then takes ~30 s.
Because there is no large model to download this is much faster than the
previous deployment, but if the booking page cannot tolerate it, either
upgrade the instance or ping `/api/health` every 10 minutes to keep it warm.

**Updating data.** Replace the relevant JSON file and push. No rebuild logic:

| File | When to update |
|---|---|
| `festivals.json` | annually — festival dates are luni-solar |
| `places.json` | when new government visitor data is collected |
| `tours.json` | when the package catalogue changes |

**Run the tests before pushing any change:**

```bash
python test_engine.py     # must be 17 passed, 0 failed
```
