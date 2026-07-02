# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

datas = [
    ('templates',    'templates'),
    ('static',       'static'),
    ('Tesseract-OCR','Tesseract-OCR'),
    ('TinyLlama',    'TinyLlama'),      # SLM: bundles the .gguf model file
]
binaries = []
hiddenimports = []
datas += copy_metadata('en_core_web_sm')
tmp_ret = collect_all('en_core_web_sm')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# SLM: Collect llama_cpp native binaries (.dll) and hidden imports
try:
    tmp_llama = collect_all('llama_cpp')
    datas      += tmp_llama[0]
    binaries   += tmp_llama[1]
    hiddenimports += tmp_llama[2]
except Exception:
    pass  # llama_cpp not installed — SLM features disabled in build


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LogDigitizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LogDigitizer',
)
