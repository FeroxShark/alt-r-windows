# PyInstaller: pyinstaller altr.spec   ->   dist/AltR.exe (un solo archivo, sin consola)
from PyInstaller.utils.hooks import collect_data_files

datas = [
    ("altr/config.default.toml", "altr"),
    ("altr/qml", "altr/qml"),          # Overlay.qml, settings/Settings.qml y las fuentes Inter
] + collect_data_files("certifi")

# Qt de más: AltR sólo usa QtCore/QtGui/QtWidgets (bandeja) y QtQuick/QtQml (overlay, render por
# software). Lo demás que trae PySide6 se deja afuera para que el .exe no pese cientos de MB.
QT_UNUSED = [
    "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras",
    "QtBluetooth", "QtCharts", "QtDataVisualization", "QtDesigner", "QtHelp", "QtLocation",
    "QtMultimedia", "QtMultimediaWidgets", "QtNfc", "QtPdf", "QtPdfWidgets", "QtPositioning",
    "QtQuick3D", "QtRemoteObjects", "QtScxml", "QtSensors", "QtSerialPort", "QtSql", "QtTest",
    "QtTextToSpeech", "QtWebChannel", "QtWebEngineCore", "QtWebEngineQuick", "QtWebEngineWidgets",
    "QtWebSockets", "QtWebView", "QtOpenGLWidgets",
    "QtSpatialAudio", "QtGraphs", "QtVirtualKeyboard", "QtQuickControls2", "QtQuickDialogs2",
    "QtQuickTemplates2", "QtQuickWidgets", "QtQuickTest",
]
# Qt trae módulos de QML (Controls, Dialogs...) y archivos sueltos que este overlay no importa
# (sólo usa `import QtQuick`).
DROP_PATHS = (
    "qml/QtQuick/Controls", "qml/QtQuick/Dialogs", "qml/QtQuick/Templates", "qml/QtQuick/NativeStyle",
    "qml/QtQuick/Layouts", "qml/QtQuick/Effects", "qml/QtQuick/Particles", "qml/QtQuick/Shapes",
    "qml/QtQuick/VirtualKeyboard", "qml/QtQuick/LocalStorage", "qml/QtQuick/Pdf", "qml/QtQuick3D",
    "qml/QtQuick/Scene2D", "qml/QtQuick/Scene3D", "qml/Qt3D", "qml/QtCharts", "qml/QtMultimedia",
    "qml/QtWebEngine", "qml/QtWebView", "qml/QtSensors", "qml/QtPositioning", "qml/QtLocation",
    "qml/QtTest", "qml/Qt5Compat", "qml/QtDataVisualization", "qml/QtGraphs", "qml/QtRemoteObjects",
    "PySide6/translations", "opengl32sw.dll", "d3dcompiler_47.dll",
)


def _keep(item):
    dest = item[0].replace("\\", "/")
    return not any(p in dest for p in DROP_PATHS)


a = Analysis(
    ["run_altr.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=["altr.win", "altr.ui", "altr.settings", "altr.updates", "altr.secrets", "tomlkit",
                   "keyring", "keyring.backends.Windows", "altr.demo", "altr.app",
                   "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtQml",
                   "PySide6.QtQuick"],
    excludes=["tkinter", "unittest", "pydoc", "test"] + [f"PySide6.{m}" for m in QT_UNUSED],
)
a.datas = [d for d in a.datas if _keep(d)]
a.binaries = [b for b in a.binaries if _keep(b)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AltR",
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
