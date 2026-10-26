# PyInstaller: pyinstaller altr.spec   ->   dist/AltR.exe (un solo archivo, sin consola)
from PyInstaller.utils.hooks import collect_data_files

datas = [("altr/config.default.toml", "altr")] + collect_data_files("certifi")

a = Analysis(
    ["run_altr.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=["altr.win", "altr.tray", "altr.app", "pystray._win32"],
    excludes=["tkinter", "unittest", "pydoc", "test"],
)
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
