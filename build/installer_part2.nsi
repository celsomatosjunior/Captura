; Capture Pro — parte 2 do instalador (componente de captura OpenCV).
; É executada automaticamente pelo CapturePro-Setup-<versão>.exe.
Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 64
RequestExecutionLevel admin
!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!ifndef DISTDIR
  !define DISTDIR "..\dist\CapturePro"
!endif
!ifndef OUTFILE
  !define OUTFILE "CapturePro-Setup-${VERSION}-parte2.exe"
!endif
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

Name "Capture Pro ${VERSION} (parte 2)"
OutFile "${OUTFILE}"
Icon "..\assets\icon.ico"
InstallDir "$PROGRAMFILES64\Capture Pro"
SilentInstall silent
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Capture Pro"
VIAddVersionKey "FileDescription" "Capture Pro - componente de captura (parte 2)"
VIAddVersionKey "FileVersion" "${VERSION}"

Var standalone

Function .onInit
  SetRegView 64
  StrCpy $standalone "0"
  ${GetParameters} $R0
  ${GetOptions} $R0 "/S" $R1
  ${If} ${Errors}
    ; aberto diretamente pelo usuário
    StrCpy $standalone "1"
    ReadRegStr $R2 HKLM "Software\CapturePro" "InstallDir"
    ${If} $R2 == ""
      MessageBox MB_ICONINFORMATION "Este arquivo é a parte 2 do instalador.$\n$\nAbra o arquivo CapturePro-Setup-${VERSION}.exe (deixe os dois arquivos na mesma pasta)."
      Abort
    ${EndIf}
    StrCpy $INSTDIR $R2
  ${EndIf}
FunctionEnd

Section
  SetOutPath "$INSTDIR\Lib\site-packages\cv2"
  File /r "${DISTDIR}\Lib\site-packages\cv2\*.*"
  ${If} $standalone == "1"
    MessageBox MB_ICONINFORMATION "Componente de captura do Capture Pro instalado."
  ${EndIf}
SectionEnd
