# PyInstaller spec for LivelyRec
#
# Build:
#   pyinstaller LivelyRec.spec
#
# 出力: dist/LivelyRec/LivelyRec.exe（--onedir）
# 配布: dist/LivelyRec/ をフォルダごと ZIP 化
#
# 詳細: docs/design/06_詳細設計_アーキテクチャ.md §10

# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

block_cipher = None

# PaddleOCR は Cython を実行時にロードして .cpp/.pxi 等のユーティリティを使うため、
# ソース込みで丸ごと同梱しないと "Cython/Utility/CppSupport.cpp not found" になる。
hidden = []
hidden += collect_submodules("paddleocr")
hidden += collect_submodules("paddle")
hidden += collect_submodules("obswebsocket")
hidden += collect_submodules("Cython")
hidden += collect_submodules("scipy")
# PaddleOCR の DB postprocess / preprocess が動的に require するモジュール
hidden += [
    "pyclipper",
    "shapely",
    "shapely.geometry",
    "shapely.geos",
    "imgaug",
    "imgaug.augmenters",
    "lmdb",
    "skimage",
    "skimage.morphology",
    "skimage.measure",
    "PIL.Image",
    "imghdr",  # PaddleOCR ppocr.utils.utility が利用
]

datas = []
datas += [("browser_source", "browser_source")]
datas += [("templates", "templates")]
# 楽曲マスタの seed（オフライン初回起動・エンドポイント未設定時のフォールバック）
datas += [("data/master.json", "data")]
# PaddleOCR は tools/, ppocr/, ppstructure/ 配下の .py を動的 import するため
# include_py_files=True で同梱する必要がある（pyimod02_importers では辿れない）
datas += collect_data_files("paddleocr", include_py_files=True)
datas += collect_data_files("paddle", include_py_files=True)
datas += collect_data_files("Cython", include_py_files=True)
datas += collect_data_files("paddlex", include_py_files=True)

# PaddleOCR の依存パッケージは importlib.metadata.version("xxx") を起動時に呼ぶため、
# dist-info メタデータの同梱が必要。
for pkg in [
    "imageio", "shapely", "paddleocr", "paddlepaddle",
    "opencv-contrib-python", "opencv-python-headless", "opencv-python",
    "scipy", "numpy", "Pillow", "scikit-image", "imgaug", "lmdb",
    "pyclipper", "tqdm", "fire", "rapidfuzz", "PyYAML", "jaconv",
    "paddlex", "lxml", "premailer", "requests", "PySide6",
    "obs-websocket-py", "websocket-client", "websockets", "Cython",
]:
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass  # 一部のパッケージは別名で登録されていることがある

# 不要な大物パッケージを除外して配布サイズを抑える。
# PaddleOCR は OCR 機能だけ使うので、表計算/可視化/ML 用の依存は不要。
excludes = [
    "docs", "poc", "tests", "livelyrec_data",
    # 大物パッケージ（OCRに不要）
    "tensorflow", "torch", "torchvision", "torchaudio",
    "matplotlib", "matplotlib.tests",
    "sympy",
    "IPython", "ipykernel", "jupyter", "notebook",
    "pandas.tests",
    "scipy.tests",
    # skimage / imgaug は PaddleOCR の前処理で利用するため exclude しない
    "pdf2docx", "openpyxl",
    "visualdl",
    "PyMuPDF", "fitz",
    "PyQt5", "PyQt6",
    "tkinter",
]

a = Analysis(
    ["livelyrec/app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LivelyRec",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="LivelyRec",
)
