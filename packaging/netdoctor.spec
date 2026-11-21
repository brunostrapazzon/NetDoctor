# PyInstaller: gera dois executáveis de arquivo único em dist/
#   NetDoctor.exe      interface do Modo Cliente, sem console
#   netdoctor-cli.exe  linha de comando (diagnose, --json, --html)
#
#   .venv\Scripts\pyinstaller --noconfirm --clean packaging\netdoctor.spec
#
# O customtkinter e o dnspython têm hooks no pyinstaller-hooks-contrib, então não
# precisam de --add-data. Os dados do próprio NetDoctor (thresholds.toml e o ícone)
# entram por collect_data_files("netdoctor").
# ruff: noqa

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

from netdoctor import __version__

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "netdoctor" / "ui" / "netdoctor.ico")
DATAS = collect_data_files("netdoctor")
# Nada disso é usado; deixar de fora diminui o .exe.
EXCLUDES = ["pytest", "_pytest", "ruff", "PIL", "numpy", "unittest", "pydoc_data"]


def version_info(original_name, description):
    nums = tuple(int(p) for p in __version__.split(".")[:3]) + (0,)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "041604B0",  # pt-BR, Unicode
                        [
                            StringStruct("CompanyName", "Bruno Strapazzon"),
                            StringStruct("FileDescription", description),
                            StringStruct("FileVersion", __version__),
                            StringStruct("InternalName", original_name.removesuffix(".exe")),
                            StringStruct("LegalCopyright", "(c) 2026 Bruno Strapazzon. PolyForm Noncommercial 1.0.0"),
                            StringStruct("OriginalFilename", original_name),
                            StringStruct("ProductName", "NetDoctor"),
                            StringStruct("ProductVersion", __version__),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
        ],
    )


def build(script, name, console, description):
    a = Analysis(
        [str(ROOT / "packaging" / script)],
        pathex=[str(ROOT)],
        datas=DATAS,
        excludes=EXCLUDES,
    )
    pyz = PYZ(a.pure)
    return EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name=name,
        console=console,
        icon=ICON,
        version=version_info(f"{name}.exe", description),
        upx=False,  # UPX aumenta falsos positivos de antivírus
    )


gui = build("netdoctor_gui.py", "NetDoctor", False, "NetDoctor - diagnóstico de internet")
cli = build("netdoctor_cli.py", "netdoctor-cli", True, "NetDoctor - linha de comando")
