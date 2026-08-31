# Security Policy

## Supported versions

Only the latest release is supported. Desktop Scanner updates itself: an
installed copy (1.0.1 or newer) checks for a new release on launch and
offers to install it. Always run the newest version.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting instead:

1. Go to the **[Security tab](https://github.com/manasij123/desktop-scanner/security)**
   of this repository.
2. Click **"Report a vulnerability"**.
3. Describe the issue, the version affected, and steps to reproduce.

You'll get a response within a few days. Once a fix is ready it ships as a
normal release and installed copies pick it up automatically.

## Scope

Desktop Scanner runs entirely offline — it makes no network requests
except the update check against the GitHub Releases API, and the update
download from GitHub itself. It reads image/PDF files you point it at and
writes image/PDF/text files you ask it to. Relevant areas for a report:

- the update mechanism (`clearscanner/core/updater.py`) — e.g. a way to
  get a malicious payload installed;
- file parsing (`clearscanner/core/pdf_import.py`, image loading) — e.g. a
  crafted PDF or image that does more than fail to open;
- the bundled third-party components (PySide6/Qt, OpenCV, PyMuPDF,
  onnxruntime, Tesseract) — please also report those upstream.
