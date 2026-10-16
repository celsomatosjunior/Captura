#!/usr/bin/env bash
# Gera a distribuição Windows x64 completa (pasta portátil, instalador e .zip).
# Roda em Linux (Ubuntu 24.04) com: python3.12, mingw-w64, nsis, pip.
#   sudo apt install nsis gcc-mingw-w64-x86-64
#   ./build/build.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
VERSION=$(python3 -c "import re;print(re.search(r'__version__ = \"(.+?)\"', open('src/capturepro/__init__.py').read()).group(1))")
WORK=${WORK:-$ROOT/.build}
DIST=$ROOT/dist
PYTAG=20250115
PYVER=3.12.8
mkdir -p "$WORK" "$DIST"

echo "== 1/6 Python $PYVER para Windows (python-build-standalone)"
if [ ! -d "$WORK/winpy/python" ]; then
  curl -sSL -o "$WORK/py.tar.gz" \
    "https://github.com/astral-sh/python-build-standalone/releases/download/$PYTAG/cpython-$PYVER%2B$PYTAG-x86_64-pc-windows-msvc-install_only.tar.gz"
  mkdir -p "$WORK/winpy" && tar xzf "$WORK/py.tar.gz" -C "$WORK/winpy"
fi

echo "== 2/6 Dependências (wheels win_amd64)"
mkdir -p "$WORK/wheels"
python3 -m pip download -q --only-binary=:all: --platform win_amd64 --python-version 3.12 \
  --implementation cp -d "$WORK/wheels" -r build/requirements-windows.txt

echo "== 3/6 Ícone e lançador nativo (CapturePro.exe)"
python3 build/make_icon.py assets
cp assets/icon.png src/capturepro/resources/icon.png
( cd build/launcher
  x86_64-w64-mingw32-windres launcher.rc -O coff -o launcher.res
  x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows -Wall -o CapturePro.exe launcher.c launcher.res \
      -lshell32 -static -static-libgcc )

echo "== 4/6 Montagem da pasta do programa"
python3 build/assemble.py "$WORK/winpy/python" "$WORK/wheels" build/launcher/CapturePro.exe "$DIST/CapturePro"

echo "== 5/6 Instalador único"
( cd build
  makensis -V2 -DVERSION="$VERSION" -DDISTDIR="$DIST/CapturePro" \
    -DOUTFILE="$DIST/CapturePro-Setup-$VERSION.exe" installer.nsi )

echo "== 6/6 Versão portátil (.zip completo)"
( cd "$DIST" && rm -f "CapturePro-Portatil-$VERSION.zip" && zip -qr9 "CapturePro-Portatil-$VERSION.zip" CapturePro )
ls -lh "$DIST"
