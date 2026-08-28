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

1. Bump the version in **three** places: `installer/DesktopScanner.iss`
   (`MyAppVersion`), `docs/index.html` (`DS_RELEASE.version` **and**
   `DS_RELEASE.asset`), and the visible `v1.0.0` / size text in
   `docs/index.html` and `README.md`.
2. Rebuild:

   ```bash
   venv\Scripts\pyinstaller "Desktop Scanner.spec" --noconfirm
   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\DesktopScanner.iss
   ```

3. Commit the page/version changes, `git push`.
4. `gh release create vX.Y.Z "installer/Output/DesktopScanner-Setup-X.Y.Z.exe" --title "…" --notes "…"`

The page always points at `/releases/latest/…`, so it picks up the newest
release automatically once `DS_RELEASE.asset` matches the new filename.

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
