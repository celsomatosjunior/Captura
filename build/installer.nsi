; Instalador do Capture Pro (NSIS 3, Modern UI 2)
Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 64
ManifestDPIAware true
RequestExecutionLevel admin

!define APPNAME "Capture Pro"
!define APPEXE "CapturePro.exe"
!define COMPANY "Capture Pro"
!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!ifndef DISTDIR
  !define DISTDIR "..\dist\CapturePro"
!endif
!ifndef OUTFILE
  !define OUTFILE "CapturePro-Setup-${VERSION}.exe"
!endif
!define PART2 "CapturePro-Setup-${VERSION}-parte2.exe"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\CapturePro"

Name "${APPNAME}"
OutFile "${OUTFILE}"
InstallDir "$PROGRAMFILES64\Capture Pro"
InstallDirRegKey HKLM "Software\CapturePro" "InstallDir"
BrandingText "${APPNAME} ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1046 "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=1046 "FileDescription" "Instalador do ${APPNAME}"
VIAddVersionKey /LANG=1046 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1046 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1046 "CompanyName" "${COMPANY}"
VIAddVersionKey /LANG=1046 "LegalCopyright" "${COMPANY}"

!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "LogicLib.nsh"

!define MUI_ICON "..\assets\icon.ico"
!define MUI_UNICON "..\assets\icon.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APPEXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o Capture Pro agora"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "O Capture Pro requer Windows 64 bits."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "O Capture Pro requer Windows 10 ou Windows 11."
    Abort
  ${EndIf}
  SetRegView 64
  ; o instalador é dividido em dois arquivos (limite de tamanho de download)
  IfFileExists "$EXEDIR\${PART2}" part2ok
    MessageBox MB_ICONEXCLAMATION|MB_OK "Falta o arquivo ${PART2}.$\n$\nBaixe os DOIS arquivos do Capture Pro para a mesma pasta e execute novamente este instalador." /SD IDOK
    Abort
  part2ok:
FunctionEnd

Section "Capture Pro (obrigatório)" SecMain
  SectionIn RO
  SetShellVarContext all
  ; fecha versão anterior em execução, se houver
  nsExec::Exec 'taskkill /IM ${APPEXE} /F'
  ; remove arquivos da versão anterior (mantém as configurações do usuário)
  RMDir /r "$INSTDIR\Lib"
  RMDir /r "$INSTDIR\DLLs"
  RMDir /r "$INSTDIR\app"
  SetOutPath "$INSTDIR"
  File /r /x cv2 "${DISTDIR}\*.*"
  ; segunda parte: componente de captura de vídeo (OpenCV)
  DetailPrint "Instalando o componente de captura de vídeo..."
  ExecWait '"$EXEDIR\${PART2}" /S /D=$INSTDIR' $0
  IfFileExists "$INSTDIR\Lib\site-packages\cv2\cv2.pyd" cv2ok
    MessageBox MB_ICONSTOP "Não foi possível instalar o componente de captura (código $0).$\nVerifique se o arquivo ${PART2} está completo e execute novamente." /SD IDOK
    Abort
  cv2ok:
  WriteUninstaller "$INSTDIR\Desinstalar.exe"

  CreateDirectory "$SMPROGRAMS\Capture Pro"
  CreateShortcut "$SMPROGRAMS\Capture Pro\Capture Pro.lnk" "$INSTDIR\${APPEXE}" "" "$INSTDIR\${APPEXE}" 0
  CreateShortcut "$SMPROGRAMS\Capture Pro\Desinstalar Capture Pro.lnk" "$INSTDIR\Desinstalar.exe"

  WriteRegStr HKLM "Software\CapturePro" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINSTKEY}" "Publisher" "${COMPANY}"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\${APPEXE}"
  WriteRegStr HKLM "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoRepair" 1
SectionEnd

Section "Atalho na Área de Trabalho" SecDesktop
  SetShellVarContext all
  CreateShortcut "$DESKTOP\Capture Pro.lnk" "$INSTDIR\${APPEXE}" "" "$INSTDIR\${APPEXE}" 0
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "Programa Capture Pro com todos os componentes necessários."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Cria um ícone do Capture Pro na Área de Trabalho."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function un.onInit
  SetRegView 64
FunctionEnd

Section "Uninstall"
  SetShellVarContext all
  nsExec::Exec 'taskkill /IM ${APPEXE} /F'
  Delete "$DESKTOP\Capture Pro.lnk"
  RMDir /r "$SMPROGRAMS\Capture Pro"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKLM "${UNINSTKEY}"
  DeleteRegKey HKLM "Software\CapturePro"
  ; remove a inicialização automática, se tiver sido ativada
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "CapturePro"
  ; as imagens capturadas e as configurações do usuário NÃO são apagadas
SectionEnd
