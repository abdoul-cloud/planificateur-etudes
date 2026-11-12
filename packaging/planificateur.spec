# Recette PyInstaller : application autonome dans build/dist/PlanificateurEtudes/
#   .venv/Scripts/python.exe -m PyInstaller packaging/planificateur.spec --noconfirm --distpath build/dist --workpath build/work
from pathlib import Path

RACINE = Path(SPECPATH).parent
PAQUET = RACINE / "planificateur"

a = Analysis(
    [str(RACINE / "packaging" / "point_entree.py")],
    pathex=[str(RACINE)],
    datas=[
        (str(PAQUET / "schema.sql"), "planificateur"),
        (str(PAQUET / "ui" / "images"), "planificateur/ui/images"),
    ],
    # Les flèches et coches de l'interface sont des SVG : il faut le module Qt SVG.
    hiddenimports=["PySide6.QtSvg"],
    excludes=[
        "tkinter", "unittest", "pydoc",
        "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets", "PySide6.QtMultimedia", "PySide6.Qt3DCore", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PlanificateurEtudes",
    console=False,
    icon=str(RACINE / "packaging" / "icone.ico"),
    version=str(RACINE / "packaging" / "version.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="PlanificateurEtudes")
