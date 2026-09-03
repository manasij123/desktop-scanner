# Deploying the web app

| Piece | Where | Cost |
|---|---|---|
| **Frontend** (`webapp/` → `docs/app/`) | GitHub Pages, `manasij123.github.io/desktop-scanner/app/` | free |
| **Backend** (`Dockerfile` + `server/`) | Fly.io | ~$1-4/mo (scale-to-zero) |

The frontend works on its own (on-device WebGL). The backend is **opt-in** — a
user connects it from the *On-device / Server* chip for desktop-grade output.

---

## 1. Backend → Fly.io

Needs a Fly.io account (a card, **no ID/KYC**). The machine scales to zero when
idle, so a low-traffic app costs a dollar or two a month.

### First deploy (from your machine)

1. **Install flyctl** — <https://fly.io/docs/flyctl/install/>
   - Windows (PowerShell): `iwr https://fly.io/install.ps1 -useb | iex`
   - then open a **new** terminal so `fly` is on PATH
2. **Sign in / up:**
   ```sh
   fly auth signup      # or: fly auth login
   ```
3. **From the repo root** (`f:\Projects\DesktopScanner`), create the app from
   the checked-in `fly.toml` (does **not** deploy yet):
   ```sh
   fly launch --no-deploy --copy-config --name desktop-scanner-api --region bom
   ```
   - "Would you like to adjust settings?" → **No**
   - if it says the name is taken, pick another and update `app =` in `fly.toml`
4. **Deploy** (builds the image on Fly's builder — no local Docker needed):
   ```sh
   fly deploy
   ```
   First build ~6-10 min. The URL is `https://desktop-scanner-api.fly.dev`
   (or your chosen name). Check:
   ```sh
   curl https://desktop-scanner-api.fly.dev/health
   ```
   `{"ok":true,...}` → live.

### Auto-deploy on push (optional)

```sh
fly tokens create deploy -x 999999h
```
Copy the token → repo **Settings → Secrets and variables → Actions → New
repository secret** → `FLY_API_TOKEN`. After that, any push touching
`Dockerfile` / `fly.toml` / `server/**` / `clearscanner/**` redeploys via
`.github/workflows/deploy-api.yml`.

### Notes

- **Cold start** — `auto_stop_machines` in `fly.toml` stops the machine when
  idle; the next request wakes it in ~10 s (the u2netp model is baked into the
  image, no download). The frontend health check retries patiently.
- **CORS** — set in `fly.toml` `[env]` as `DSC_ALLOW_ORIGINS`. Change it there
  and `fly deploy`, or `fly secrets set DSC_ALLOW_ORIGINS=https://…`.
- **Memory** — `1gb` fits opencv + onnxruntime + rembg with
  `DSC_CACHE_SCALE=0.6`. Drop to `512mb` only if you also remove `rembg` +
  `onnxruntime` from `server/requirements.txt` (classical detection only).
- **Logs / status** — `fly logs`, `fly status`.

### Other hosts

The root `Dockerfile` honours `$PORT` and runs anywhere.

- **Google Cloud Run** (free tier, but India billing needs Aadhaar/address
  verification): `bash server/gcp-setup.sh` then push, or
  `gcloud run deploy desktop-scanner-api --source . --region asia-south1 --memory 1Gi --cpu 1 --allow-unauthenticated --set-env-vars DSC_ALLOW_ORIGINS=https://manasij123.github.io`
- **Render** (free, no card — but 0.1 CPU is slow for rembg): new Web Service
  from the repo, Docker env, `/health` health check path.
- **Local:** `docker build -t dsc-api . && docker run -p 8080:8080 -e DSC_ALLOW_ORIGINS='*' dsc-api`

---

## 2. Point the frontend at the backend

Put the URL from step 1 into **`webapp/public/config.json`**:

```json
{ "apiUrl": "https://desktop-scanner-api.fly.dev", "serverDefault": false }
```

- `apiUrl` — offered in the *Processing server* dialog as **Use hosted server**
  (empty = on-device only, no offer).
- `serverDefault` — `false` keeps **on-device** the default (nothing uploaded
  unless the user opts in). `true` auto-connects on load.

Then:

```sh
cd webapp && npm run build
git add -A && git commit -m "web: connect hosted backend" && git push
```

---

## 3. Privacy

On-device mode uploads nothing. In server mode the web app POSTs a **downscaled
JPEG** (not the raw phone file) per detect/render; the backend is **stateless**
— no disk writes, no logging of image bytes. Still, that's someone's ID on a
cloud host, which is why `serverDefault` is `false`.
