# Componentes de terceiros

O Capture Pro é distribuído junto com os componentes abaixo, cada um sob sua
própria licença. Nenhum deles foi modificado.

| Componente | Versão | Licença | Site |
|---|---|---|---|
| Python (CPython, build python-build-standalone) | 3.12.8 | PSF License | https://www.python.org |
| Qt for Python (PySide6-Essentials, shiboken6) | 6.12.0 | LGPL v3 | https://www.qt.io/qt-for-python |
| Qt 6 (bibliotecas incluídas no PySide6) | 6.12 | LGPL v3 | https://www.qt.io |
| OpenCV (opencv-python-headless) | 4.14.0 | Apache 2.0 | https://opencv.org |
| NumPy (inclui OpenBLAS) | 2.5.4 | BSD-3-Clause | https://numpy.org |
| comtypes | 1.4.17 | MIT | https://github.com/enthought/comtypes |
| pygrabber | 0.2 | MIT | https://github.com/andreaschiavinato/python_grabber |
| Microsoft Visual C++ Runtime (msvcp140, vcruntime140, concrt140) | 14.x | Licença de redistribuição da Microsoft | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |

## Observação sobre a LGPL (Qt / PySide6)

As bibliotecas Qt e PySide6 são usadas como bibliotecas dinâmicas (arquivos
`.dll`/`.pyd` em `Lib\site-packages\PySide6`), sem modificação. O usuário pode
substituí-las por outra versão compatível. O código-fonte do Qt e do PySide6
está disponível nos sites acima. O texto completo das licenças acompanha cada
pacote na pasta `Lib\site-packages\<pacote>-<versão>.dist-info`.
