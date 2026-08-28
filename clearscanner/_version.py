__version__ = "1.0.1"
# ^ Single source of truth for the app version. Bump the string, then
# rebuild. Both the running app (clearscanner.core.updater) and the Inno
# Setup installer (installer/DesktopScanner.iss reads this file's first
# line) pick it up. Keep the visible version in docs/index.html in sync too.
