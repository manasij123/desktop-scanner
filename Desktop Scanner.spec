# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('clearscanner/assets', 'clearscanner/assets')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rembg')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cv2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pymupdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# requests + its runtime deps — the auto-updater (clearscanner.core.updater)
# needs these, and certifi ships a data file (cacert.pem) that must come along.
tmp_ret = collect_all('certifi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
hiddenimports += ['requests', 'charset_normalizer', 'urllib3', 'idna']
# QtSvg backs the line-icon rendering in clearscanner.ui.icons.
# QtNetwork backs main.py's single-instance file handoff (QLocalServer).
hiddenimports += ['PySide6.QtSvg', 'PySide6.QtNetwork']


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing here needs an interactive shell — jedi alone is ~22 MB.
    # (tkinter is kept: the PyInstaller splash below uses Tk.)
    excludes=['IPython', 'jedi', 'parso'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Bootloader-level splash — a static image shown the instant the process
# starts, seconds before Python/Qt finish loading on a cold run. main.py
# closes it via pyi_splash once the animated Qt splash takes over.
splash = Splash(
    'clearscanner/assets/splash_static.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    minify_script=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    [],
    exclude_binaries=True,
    name='Desktop Scanner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['clearscanner/assets/icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Desktop Scanner',
)
