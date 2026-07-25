# VoiceTask — cloud edition

Same app as the desktop version, but as a website: a FastAPI backend +
a mobile-friendly page that uses your phone's built-in voice recognition
(Safari on iPhone, Chrome on Android — no app install needed).

```
voicetask-cloud/
├── backend/          FastAPI app (API + serves the frontend)
│   ├── main.py
│   ├── storage.py     SQLite locally, Turso (cloud) in production
│   ├── excel_io.py
│   ├── llm_parser.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── index.html      the whole UI, one file
└── render.yaml          Render deploy config
```

## 1. Get a free database (Turso)

1. Go to https://turso.tech and sign up free.
2. Create a database (any name, e.g. `voicetask`).
3. From its dashboard, grab:
   - the **Database URL** (starts with `libsql://...`)
   - an **Auth Token** (create one under the database's settings)

You'll paste both into Render in step 3. The free tier covers a personal
task list many times over.

## 2. Get a Claude API key

1. https://console.anthropic.com → API Keys → create one.
2. Voice parsing costs a fraction of a cent per command on the Haiku model
   this app uses — a personal task list won't come close to noticeable cost.

## 3. Push this project to GitHub

```bash
cd voicetask-cloud
git init
git add .
git commit -m "VoiceTask cloud"
```
Create a new repo on GitHub, then:
```bash
git remote add origin https://github.com/<you>/voicetask.git
git push -u origin main
```

## 4. Deploy on Render (free)

1. https://render.com → sign up free → **New +** → **Web Service**.
2. Connect your GitHub repo. Render will detect `render.yaml` automatically
   and pre-fill the settings (root dir `backend`, build/start commands).
3. When prompted, fill in the environment variables:
   - `ANTHROPIC_API_KEY` → your key from step 2
   - `TURSO_DATABASE_URL` → from step 1
   - `TURSO_AUTH_TOKEN` → from step 1
4. Click **Create Web Service**. First deploy takes a couple of minutes.
5. You'll get a URL like `https://voicetask-xxxx.onrender.com` — that's your
   whole app, frontend and backend, live.

**Free-tier note:** the service sleeps after ~15 minutes idle. The first
request after that takes ~30 seconds to wake up — totally fine for personal
use, just don't expect instant response the first time each day.

## 5. Use it on your phone

Open the Render URL in Safari (iPhone) or Chrome (Android). Tap the mic
button, allow microphone access when asked, and speak a command.

**Add it to your home screen so it feels like an app:**
- iPhone (Safari): Share icon → "Add to Home Screen"
- Android (Chrome): ⋮ menu → "Add to Home screen"

## 6. Local development

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY; leave TURSO_* blank to use a local file
uvicorn main:app --reload
```
Then open http://localhost:8000 in your browser. Voice input needs HTTPS
in most browsers except on localhost, so this works fine for local testing.

## API reference

| Method | Path | What it does |
|---|---|---|
| GET | `/api/tasks` | List tasks (`?status=&priority=`) |
| POST | `/api/tasks` | Add a task `{title, priority}` |
| POST | `/api/tasks/{id}/complete` | Mark done |
| DELETE | `/api/tasks/{id}` | Delete |
| PATCH | `/api/tasks/{id}/priority` | Change priority |
| POST | `/api/command` | Send raw text `{text}`, get back the parsed + executed result |
| GET | `/api/export` | Download tasks as `.xlsx` |
| POST | `/api/import` | Upload an `.xlsx` file to import |

## Next steps if you outgrow the free tier

- **Faster wake-up:** Render's paid tier ($7/mo) keeps the service always-on.
- **Custom domain:** point your own domain at the Render service for free.
- **Multiple users / accounts:** would need basic auth added to the API —
  worth doing if you ever share this beyond yourself.
