Unicode True
!include "MUI2.nsh"
Name "ChessStream PGN Recorder"
OutFile "../dist/ChessStream-PGN-Recorder-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\ChessStream PGN Recorder"
InstallDirRegKey HKCU "Software\ChessStream" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "ChessStream PGN Recorder • Local processing"
!define MUI_ABORTWARNING
!define MUI_ICON "../chessstream/assets/icon.ico"
!define MUI_UNICON "../chessstream/assets/icon.ico"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "../LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\runtime\pythonw.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "-m chessstream"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "ChessStream" SEC01
  SetOutPath "$INSTDIR"
  File /r "../build/windows-portable/*"
  WriteRegStr HKCU "Software\ChessStream" "InstallDir" "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\ChessStream PGN Recorder"
  CreateShortcut "$SMPROGRAMS\ChessStream PGN Recorder\ChessStream PGN Recorder.lnk" "$INSTDIR\runtime\pythonw.exe" "-m chessstream" "$INSTDIR\chessstream\assets\icon.ico"
  CreateShortcut "$SMPROGRAMS\ChessStream PGN Recorder\User guide.lnk" "$INSTDIR\chessstream\assets\USER_GUIDE.html"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ChessStream" "DisplayName" "ChessStream PGN Recorder"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ChessStream" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ChessStream" "DisplayVersion" "1.6.10"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ChessStream" "Publisher" "ChessStream project"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ChessStream" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ChessStream" "NoRepair" 1
SectionEnd

Section "Uninstall"
  ; The LocalAppData recordings folder is deliberately outside the installation.
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\chessstream"
  RMDir /r "$INSTDIR\docs"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  Delete "$INSTDIR\BUILD-MANIFEST.json"
  Delete "$INSTDIR\Launch ChessStream.cmd"
  Delete "$INSTDIR\Diagnose ChessStream.cmd"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  RMDir /r "$SMPROGRAMS\ChessStream PGN Recorder"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ChessStream"
  DeleteRegKey HKCU "Software\ChessStream"
SectionEnd
