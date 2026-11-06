# -*- mode: python ; coding: utf-8 -*-
import os
import sys

block_cipher = None

# In PyInstaller spec files, SPECPATH is the directory containing the spec file
ROOT = os.path.abspath(SPECPATH)

# Data files: bundle ONLY templates and static assets
# Settings (pipeline_config.json), database (queue_state.db), and pipeline_output/
# are deliberately NOT bundled so they remain external, editable, and persistent.
datas = [
    (os.path.join(ROOT, 'templates'), 'templates'),
    (os.path.join(ROOT, 'static'), 'static'),
]

hidden_imports = [
    'flask',
    'jinja2',
    'requests',
    'sqlite3',
    'PIL',
    'PIL.Image',
    'cv2',
    'bs4',
    'lxml',
    'lxml.etree',
    'newspaper',
    'nltk',
    'gflow_bridge',
    'google_sheet_sync',
    'wordpress_publisher',
    'firestore_sync',
    'ipv4_guard',
    'pipeline_engine',
    'app',
]

a = Analysis(
    [os.path.join(ROOT, 'run.py')],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'IPython',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AutoContentPipeline',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
