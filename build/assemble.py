"""Monta a distribuição Windows x64 autossuficiente do Capture Pro.

Uso: python assemble.py <python-windows-dir> <wheels-dir> <launcher.exe> <saida>

- copia o Python 3.12 para Windows (sem testes, tkinter, cabeçalhos...)
- extrai as dependências (wheels win_amd64) em Lib\\site-packages
- remove partes do Qt não usadas (QML/Quick, ferramentas, etc.)
- copia o código do aplicativo para app\\ e pré-compila tudo (.pyc)
- verifica, pelos cabeçalhos PE, que toda DLL necessária está presente
"""
from __future__ import annotations

import compileall
import fnmatch
import os
import shutil
import sys
import zipfile

import pefile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PY_REMOVE = [
    "include", "libs", "Scripts", "tcl", "Lib/test", "Lib/idlelib", "Lib/tkinter",
    "Lib/turtledemo", "Lib/ensurepip", "Lib/lib2to3", "Lib/site-packages/pip",
    "DLLs/_ssl.pyd", "DLLs/_hashlib.pyd", "DLLs/libssl-3-x64.dll", "DLLs/libcrypto-3-x64.dll",
    "DLLs/_sqlite3.pyd", "DLLs/sqlite3.dll", "DLLs/_msi.pyd", "DLLs/_testcapi.pyd",
    "DLLs/_testinternalcapi.pyd", "DLLs/_testbuffer.pyd", "DLLs/_testimportmultiple.pyd",
    "DLLs/_testmultiphase.pyd", "DLLs/_testsinglephase.pyd", "DLLs/_testconsole.pyd",
    "DLLs/_testclinic.pyd", "DLLs/_ctypes_test.pyd", "DLLs/xxlimited.pyd", "DLLs/xxlimited_35.pyd",
    "Lib/sqlite3", "Lib/msilib",
    "DLLs/_tkinter.pyd", "DLLs/tcl86t.dll", "DLLs/tk86t.dll", "DLLs/zlib1.dll.unused",
]
QT_REMOVE_GLOBS = [
    "PySide6/*.exe", "PySide6/qml", "PySide6/include", "PySide6/typesystems", "PySide6/glue",
    "PySide6/scripts", "PySide6/examples", "PySide6/metatypes", "PySide6/resources",
    "PySide6/Qt6Quick*", "PySide6/Qt6Qml*", "PySide6/Qt6Designer*", "PySide6/Qt6Pdf*",
    "PySide6/Qt6ShaderTools*", "PySide6/Qt6Help*", "PySide6/Qt6Sql*", "PySide6/Qt6Test*",
    "PySide6/Qt6UiTools*", "PySide6/Qt6Multimedia*", "PySide6/Qt6SpatialAudio*",
    "PySide6/Qt6Labs*", "PySide6/Qt6WebSockets*", "PySide6/Qt6Charts*", "PySide6/Qt6DataVis*",
    "PySide6/Qt6Graphs*", "PySide6/Qt6Concurrent*", "PySide6/Qt6Xml*", "PySide6/Qt6Positioning*",
    "PySide6/Qt6Sensors*", "PySide6/Qt6SerialPort*", "PySide6/Qt6Bluetooth*", "PySide6/Qt6Nfc*",
    "PySide6/Qt6Location*", "PySide6/Qt6RemoteObjects*", "PySide6/Qt6Scxml*", "PySide6/Qt6StateMachine*",
    "PySide6/Qt6TextToSpeech*", "PySide6/Qt6WebChannel*", "PySide6/Qt6HttpServer*", "PySide6/Qt6Quick3D*",
    "PySide6/Qt63D*", "PySide6/Qt6OpenGLWidgets*", "PySide6/Qt6SvgWidgets*",
    "PySide6/opengl32sw.dll", "PySide6/plugins/sqldrivers", "PySide6/plugins/qmltooling",
    "PySide6/plugins/qmllint", "PySide6/plugins/scenegraph", "PySide6/plugins/designer",
    "PySide6/plugins/multimedia", "PySide6/plugins/position", "PySide6/plugins/sensors",
    "PySide6/plugins/texttospeech", "PySide6/plugins/assetimporters",
    "PySide6/Quick*.pyd", "PySide6/Qml*.pyd", "PySide6/Qt*Quick*.pyd", "PySide6/QtQml*.pyd",
    "PySide6/QtDesigner*.pyd", "PySide6/QtPdf*.pyd", "PySide6/QtHelp*.pyd", "PySide6/QtSql*.pyd",
    "PySide6/QtTest*.pyd", "PySide6/QtUiTools*.pyd", "PySide6/QtMultimedia*.pyd",
    "PySide6/QtSpatialAudio*.pyd", "PySide6/QtConcurrent*.pyd", "PySide6/QtXml*.pyd",
    "PySide6/QtOpenGLWidgets*.pyd", "PySide6/QtSvgWidgets*.pyd", "PySide6/QtStateMachine*.pyd",
    "PySide6/QtWebSockets*.pyd", "PySide6/QtHttpServer*.pyd", "PySide6/QtRemoteObjects*.pyd",
    "PySide6/QtScxml*.pyd", "PySide6/QtTextToSpeech*.pyd", "PySide6/QtWebChannel*.pyd",
    "PySide6/QtCharts*.pyd", "PySide6/QtDataVis*.pyd", "PySide6/QtGraphs*.pyd",
    "PySide6/QtPositioning*.pyd", "PySide6/QtLocation*.pyd", "PySide6/QtSensors*.pyd",
    "PySide6/QtSerialPort*.pyd", "PySide6/QtBluetooth*.pyd", "PySide6/QtNfc*.pyd",
    "PySide6/Qt3D*.pyd", "PySide6/QtDBus*.pyd", "PySide6/Qt6DBus*",
    "PySide6/*.pyi", "shiboken6/*.pyi", "cv2/data", "cv2/*.pyi",
    "PySide6/pyside6qml*", "PySide6/Qt6Lottie*", "PySide6/QtLabs*", "PySide6/Qt6VirtualKeyboard*",
    "PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll", "PySide6/plugins/imageformats/qpdf.dll",
    "PySide6/plugins/vectorimageformats", "PySide6/QtVirtualKeyboard*.pyd",
    "cv2/opencv_videoio_ffmpeg*.dll", "numpy/*/tests", "numpy/tests", "numpy/_pyinstaller",
    "PySide6/QtOpenGL.pyd", "PySide6/Qt6OpenGL.dll", "PySide6/QtNetwork.pyd", "PySide6/Qt6Network.dll",
    "PySide6/plugins/platforms/qdirect2d.dll", "PySide6/plugins/platforms/qminimal.dll",
    "PySide6/plugins/platforms/qoffscreen.dll", "PySide6/plugins/networkinformation", "PySide6/plugins/tls",
    "PySide6/plugins/generic", "PySide6/plugins/imageformats/qtiff.dll", "PySide6/plugins/imageformats/qwebp.dll",
    "PySide6/plugins/imageformats/qtga.dll", "PySide6/plugins/imageformats/qwbmp.dll", "PySide6/plugins/imageformats/qicns.dll",
    "PySide6/QtSql.pyd",
    "*/__pycache__",
]
KEEP_TRANSLATIONS = ("qtbase_pt_BR.qm", "qt_pt_BR.qm")

# DLLs do sistema Windows (presentes no Windows 10/11)
SYSTEM_DLLS = {
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll", "ole32.dll",
    "oleaut32.dll", "ws2_32.dll", "winmm.dll", "version.dll", "shlwapi.dll", "comdlg32.dll",
    "comctl32.dll", "imm32.dll", "netapi32.dll", "userenv.dll", "uxtheme.dll", "dwmapi.dll",
    "d3d9.dll", "d3d11.dll", "d3d12.dll", "dxgi.dll", "dwrite.dll", "d2d1.dll", "opengl32.dll",
    "crypt32.dll", "bcrypt.dll", "secur32.dll", "iphlpapi.dll", "dnsapi.dll", "mpr.dll",
    "setupapi.dll", "cfgmgr32.dll", "wtsapi32.dll", "authz.dll", "rpcrt4.dll", "mfplat.dll",
    "mf.dll", "mfreadwrite.dll", "mfuuid.dll", "strmiids.dll", "msvcrt.dll", "ntdll.dll",
    "shcore.dll", "dcomp.dll", "wininet.dll", "winhttp.dll", "propsys.dll", "evr.dll",
    "dxva2.dll", "ncrypt.dll", "credui.dll", "wintrust.dll", "psapi.dll", "dbghelp.dll",
    "mfcore.dll", "mfsensorgroup.dll", "oleacc.dll", "uiautomationcore.dll", "wldap32.dll",
    "normaliz.dll", "msimg32.dll", "winspool.drv", "hid.dll", "powrprof.dll", "dwmapi.dll",
    "d3dcompiler_47.dll", "api-ms-win-core-synch-l1-2-0.dll", "api-ms-win-core-path-l1-1-0.dll",
    "api-ms-win-core-winrt-l1-1-0.dll", "api-ms-win-core-winrt-string-l1-1-0.dll",
    "dxcore.dll", "cabinet.dll", "wevtapi.dll", "ksuser.dll", "avrt.dll", "mmdevapi.dll",
    "msi.dll", "wsock32.dll", "avicap32.dll", "mscms.dll", "icuuc.dll", "icuin.dll", "icu.dll",
    "combase.dll", "sspicli.dll", "ntdsapi.dll", "fwpuclnt.dll", "winsta.dll", "uiautomationcore.dll",
}


def rm(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        os.remove(path)


def remove_globs(base: str, patterns: list[str]) -> int:
    n = 0
    for dirpath, dirnames, filenames in os.walk(base, topdown=True):
        rel_dir = os.path.relpath(dirpath, base).replace(os.sep, "/")
        for name in list(dirnames) + filenames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if any(fnmatch.fnmatch(rel, p) for p in patterns):
                rm(os.path.join(dirpath, name))
                if name in dirnames:
                    dirnames.remove(name)
                n += 1
    return n


def check_pe_dependencies(dist: str) -> list[str]:
    """Confere imports de todos os .dll/.pyd/.exe contra os arquivos presentes."""
    present: dict[str, list[str]] = {}
    binaries = []
    for dp, _dn, fn in os.walk(dist):
        for f in fn:
            low = f.lower()
            if low.endswith((".dll", ".pyd", ".exe")):
                present.setdefault(low, []).append(dp)
                binaries.append(os.path.join(dp, f))
    problems = []
    for b in binaries:
        try:
            pe = pefile.PE(b, fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        except Exception as e:
            problems.append(f"{b}: PE inválido ({e})")
            continue
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            dll = entry.dll.decode(errors="replace").lower()
            if dll.startswith(("api-ms-win-", "ext-ms-")) or dll in SYSTEM_DLLS:
                continue
            if dll.startswith(("ucrtbase", "vcruntime140", "msvcp140", "concrt140")) and dll in present:
                continue
            if dll not in present:
                problems.append(f"{os.path.relpath(b, dist)} precisa de {dll}")
        pe.close()
    return problems


def main() -> int:
    pywin, wheels, launcher, out = sys.argv[1:5]
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(pywin, out)
    for p in PY_REMOVE:
        rm(os.path.join(out, p))
    remove_globs(out, ["*.pdb"])

    site = os.path.join(out, "Lib", "site-packages")
    os.makedirs(site, exist_ok=True)
    for w in sorted(os.listdir(wheels)):
        if w.endswith(".whl"):
            with zipfile.ZipFile(os.path.join(wheels, w)) as z:
                z.extractall(site)
            print("  +", w)
    removed = remove_globs(site, QT_REMOVE_GLOBS)
    tr = os.path.join(site, "PySide6", "translations")
    if os.path.isdir(tr):
        for f in os.listdir(tr):
            if f not in KEEP_TRANSLATIONS:
                rm(os.path.join(tr, f))
    print(f"  {removed} itens do Qt não utilizados removidos")

    # runtime C++ ao lado do executável (necessário para o OpenCV)
    for f in ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll", "msvcp140_codecvt_ids.dll"):
        src = os.path.join(site, "PySide6", f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, f))

    # aplicativo
    app_dst = os.path.join(out, "app")
    shutil.copytree(os.path.join(ROOT, "src"), app_dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(launcher, os.path.join(out, "CapturePro.exe"))
    shutil.copy2(os.path.join(ROOT, "README.md"), os.path.join(out, "LEIA-ME.md"))
    shutil.copy2(os.path.join(ROOT, "THIRD_PARTY_LICENSES.md"), os.path.join(out, "THIRD_PARTY_LICENSES.md"))

    # bytecode: hash 'unchecked' → válido mesmo em pasta somente leitura
    ok = compileall.compile_dir(out, quiet=1, workers=0,
                                invalidation_mode=compileall.py_compile.PycInvalidationMode.UNCHECKED_HASH,
                                rx=__import__("re").compile(r"[\\/](test|tests|idle_test)[\\/]"))
    print("  bytecode:", "ok" if ok else "com avisos")

    probs = check_pe_dependencies(out)
    if probs:
        print("DEPENDÊNCIAS AUSENTES:")
        for p in probs:
            print("   ", p)
        return 2
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _d, fn in os.walk(out) for f in fn)
    print(f"  distribuição pronta: {size / 1e6:.0f} MB, dependências PE verificadas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
