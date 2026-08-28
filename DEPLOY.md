# Publishing Desktop Scanner

The download page (`docs/`) is served by **GitHub Pages**. The installer is
hosted as a **GitHub Release** asset. The page's Download button links to that
asset. Nothing is embedded in the page itself.

```
 visitor  ─►  manasij123.github.io/desktop-scanner   (the page, from docs/)
                        │  "Download for Windows"
                        ▼
          github.com/…/releases/latest/download/DesktopScanner-Setup-1.0.0.exe
```

---

## 0. One-time: confirm your GitHub username

Everything below assumes your GitHub username is **`manasij123`** and the repo
is **`desktop-scanner`**. If your username is different, replace it everywhere
first (run from the project root in Git Bash):

```bash
git grep -l 'manasij123' | xargs sed -i 's#manasij123#YOUR_USERNAME#g'
```

The username / repo appears in: `docs/index.html` (the `DS_RELEASE` block near
the top — this is what the Download button uses), `README.md`.

---

## 1. First push

The local repo is already initialised and committed. Create the GitHub repo and
push:

### With the GitHub CLI (already installed at `~/bin/gh.exe`)

```bash
gh auth login          # once — pick GitHub.com, HTTPS, log in via browser
gh repo create desktop-scanner --public --source=. --remote=origin --push
```

### Or manually

1. Create a new **public** repo named `desktop-scanner` on github.com — no
   README, no .gitignore, no license (they already exist here).
2. Then:

```bash
git remote add origin https://github.com/manasij123/desktop-scanner.git
git branch -M main
git push -u origin main
```

---

## 2. Turn on GitHub Pages

Repo **Settings → Pages**:

- **Source:** Deploy from a branch
- **Branch:** `main`, folder **`/docs`** → Save

Two minutes later the site is live at
`https://manasij123.github.io/desktop-scanner/`.

---

## 3. Publish the installer as a Release

The built installer is at `installer/Output/DesktopScanner-Setup-1.0.0.exe`
(167 MB). It is **not** in git — it only lives on the Release.

### With the GitHub CLI

```bash
gh release create v1.0.0 \
  "installer/Output/DesktopScanner-Setup-1.0.0.exe" \
  --title "Desktop Scanner 1.0.0" \
  --notes "First public release. Windows 10/11 64-bit. Per-user install, no admin needed."
```

### Or manually

Repo → **Releases → Draft a new release** → tag `v1.0.0` → drag
`DesktopScanner-Setup-1.0.0.exe` into the assets box → **Publish release**.

That's it. `https://manasij123.github.io/desktop-scanner/` now has a working
Download button.

---

## Shipping a new version later

1. **`clearscanner/_version.py`** — bump the `__version__` string. This is
   the source of truth: the running app reads it, and the installer script
   reads its first line, so they can't disagree.
2. `docs/index.html` — bump `DS_RELEASE.version` **and** `DS_RELEASE.asset`,
   and the visible `v1.0.x` / size text. (`README.md` too if you keep a
   version there.)
3. Rebuild:

   ```bash
   venv\Scripts\pyinstaller "Desktop Scanner.spec" --noconfirm
   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\DesktopScanner.iss
   ```
   Output filename tracks the version: `DesktopScanner-Setup-<version>.exe`.

4. Commit, `git push`.
5. `gh release create vX.Y.Z "installer/Output/DesktopScanner-Setup-X.Y.Z.exe" --title "…" --notes "…"`

The website always links to `/releases/latest/…`, and **every installed
copy auto-updates itself** (below) — so once the release is published, you
don't have to tell anyone.

---

## Auto-update (how installed copies stay current)

From v1.0.1 on, the app updates itself:

- On launch, a background thread hits
  `api.github.com/repos/manasij123/desktop-scanner/releases/latest` and
  compares `tag_name` with the built-in `__version__`.
- If the release is newer, it downloads that release's
  `DesktopScanner-Setup-*.exe` quietly, then offers **Install & Restart**
  or **Install on Exit**. Either way it runs the installer with
  `/VERYSILENT` — an in-place upgrade (same `AppId`), no admin prompt.
- All failure paths (offline, GitHub down, no `.exe` asset) are silent
  no-ops. Running from source (`python main.py`) never checks.

So the **only** manual step to push an update to everyone is publishing the
GitHub release in step 5 above. Requirements for it to work:

- The release tag must be `vX.Y.Z` (or `X.Y.Z`) and **newer** than the
  shipped `_version.py`.
- Exactly one release asset whose name ends `.exe` and contains `setup`
  (the ISS `OutputBaseFilename` already produces `DesktopScanner-Setup-…`).
- The repo stays public (the API call is unauthenticated).

v1.0.0 users have no updater — they need to grab v1.0.1 from the site once,
by hand. After that they're on the automatic track.

---

## Notes

- **SmartScreen:** the installer is unsigned, so first-run shows *"Windows
  protected your PC"* → *More info → Run anyway*. Removing this needs a paid
  code-signing certificate (~$100–300/yr). The page already explains it to
  visitors.
- **Free-account limits:** public repo required for free GitHub Pages; Release
  assets can be up to 2 GB each. Both fine here.
- **Custom domain** (optional): add a `CNAME` file under `docs/` with your
  domain and set the DNS `CNAME` to `manasij123.github.io`.
