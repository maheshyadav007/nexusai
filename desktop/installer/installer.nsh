; NexusAI side-by-side installation, built on electron-builder's NSIS installer.
;
; <install folder>\                       chosen by the user; reused automatically for updates
;   <Product>.exe                         launcher (installer\launcher.nsi); shortcuts point here
;   Uninstall <Product>.exe
;   nexusai-install.ini                   [Install] Current=<version>: the version the launcher starts
;   app-<version>\                        one complete app per version; .nexusai-complete marks it usable
;   logs\launcher.log
;
; An update only adds a folder and then switches the pointer, so files held open by the running app or by
; security scanning never block it. The app deletes old version folders later, whenever they are free.
; Failures before the pointer switch leave the previous version working. Details: docs/SIDE_BY_SIDE_UPDATES.md
;
; Exit codes (also shown to users as NX-<code>; the app maps them in desktop/layout.cjs):
;   10 NexusAI still running   11 safety check failed   12 newer version installed   13 installer inside the folder
;   20 unsupported folder      21 folder not writable   22 not enough disk space     23 cancelled: installed elsewhere
;   31 extracted files incomplete   32 version folder busy   33 launcher/uninstaller not replaceable
;   34 version switch failed   35 old program file locked
;   51 (uninstall) folder partly left behind   52 (uninstall) data partly left behind

!include LogicLib.nsh
!include FileFunc.nsh
!include WordFunc.nsh
!include nsDialogs.nsh
!include "getProcessInfo.nsh"

!define NX_POINTER "nexusai-install.ini"
!define NX_COMPLETE ".nexusai-complete"
!define NX_LAUNCHER_SOURCE "nexusai-launcher.exe"
!define NX_EXE "${PRODUCT_FILENAME}.exe"
!define NX_UNINSTALLER "Uninstall ${PRODUCT_FILENAME}.exe"
!define NX_MOVE_REPLACE 0x9 ; MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
!define NX_MOVE_PLAIN 0x8   ; MOVEFILE_WRITE_THROUGH
!if "${APP_ID}" == "com.nexusai.desktop"
  !define NX_DATA_DIR "NexusAI"
!else if "${APP_ID}" == "com.nexusai.ci"
  !define NX_DATA_DIR "NexusAI CI"
!else
  !define NX_DATA_DIR "NexusAI Pilot"
!endif

Var nxLog

!ifndef BUILD_UNINSTALLER
  !define NX "" ; function-name prefix for this pass
!else
  !define NX "un."
!endif

; ---------------------------------------------------------------- logging and failure (both passes)

Function ${NX}nxWriteLog
  Exch $R9
  Push $R8
  Push $0
  Push $1
  Push $2
  Push $3
  Push $4
  Push $5
  Push $6
  ${GetTime} "" "L" $0 $1 $2 $3 $4 $5 $6
  ClearErrors
  FileOpen $R8 "$nxLog" a
  ${IfNot} ${Errors}
    FileSeek $R8 0 END
    FileWrite $R8 "$2-$1-$0 $4:$5:$6 $R9$\r$\n"
    FileClose $R8
  ${EndIf}
  DetailPrint "$R9"
  Pop $6
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Pop $0
  Pop $R8
  Pop $R9
FunctionEnd
!macro nxLog MESSAGE
  Push `${MESSAGE}`
  Call ${NX}nxWriteLog
!macroend

; Shows what went wrong, what to do and where the details are, then exits with the code.
; Silent runs (updates started by the app) skip the dialog; the app reads the exit code instead.
Function ${NX}nxFailWith
  Exch $R1 ; message
  Exch
  Exch $R0 ; code
  !insertmacro nxLog "NX-$R0: $R1"
  MessageBox MB_OK|MB_ICONSTOP "$R1$\r$\n$\r$\nError NX-$R0. Details: $nxLog" /SD IDOK
  SetErrorLevel $R0
  Quit
FunctionEnd
!macro nxFail CODE MESSAGE
  Push ${CODE}
  Push `${MESSAGE}`
  Call ${NX}nxFailWith
!macroend

; $INSTDIR must be a dedicated folder: never a drive root and never NexusAI's data folder.
Function ${NX}nxCheckFolder
  Push $0
  Push $1
  ${GetRoot} "$INSTDIR" $0
  StrCpy $1 "$INSTDIR" "" -1
  ${If} $1 == "\"
    StrCpy $INSTDIR "$INSTDIR" -1
  ${EndIf}
  ${If} "$INSTDIR" == ""
  ${OrIf} "$INSTDIR" == "$0"
  ${OrIf} "$INSTDIR\" == "$0"
    !insertmacro nxFail 20 "NexusAI cannot be installed directly in $INSTDIR. Choose a folder, for example $0\Apps\${PRODUCT_NAME}."
  ${EndIf}
  ; Case-insensitive prefix test: is $INSTDIR the data folder or inside it?
  StrLen $1 "$APPDATA\${NX_DATA_DIR}\"
  StrCpy $1 "$INSTDIR\" $1
  ${If} $1 == "$APPDATA\${NX_DATA_DIR}\"
    !insertmacro nxFail 20 "NexusAI cannot be installed inside its own data folder ($APPDATA\${NX_DATA_DIR}). Choose another folder."
  ${EndIf}
  Pop $1
  Pop $0
FunctionEnd

; Runs check-install.ps1 and turns a refusal into a clear message and exit code.
!macro nxSafetyCheck MODE
  InitPluginsDir
  File /oname=$PLUGINSDIR\nexusai-check-install.ps1 "${PROJECT_DIR}\installer\check-install.ps1"
  ${GetProcessInfo} 0 $R0 $R1 $R2 $R3 $R4
  nxCheckAgain_${MODE}:
    !insertmacro nxLog "safety check (${MODE}) for $INSTDIR"
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\nexusai-check-install.ps1" -InstallDirectory "$INSTDIR" -AppGuid "${APP_GUID}" -Version "${VERSION}" -InstallerProcessId $R0 -Mode ${MODE} -LogFile "$nxLog"'
    Pop $R1
    Pop $R2
    ${If} $R1 != 0
      !insertmacro nxLog "safety check returned $R1: $R2"
      ${If} $R1 == 10
        MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$R2$\r$\n$\r$\nError NX-10. Details: $nxLog" /SD IDCANCEL IDRETRY nxCheckAgain_${MODE}
        SetErrorLevel 10
        Quit
      ${ElseIf} $R1 == 12
      ${OrIf} $R1 == 13
        !insertmacro nxFail $R1 "$R2"
      ${Else}
        !insertmacro nxFail 11 "NexusAI could not check that it is safe to continue. Nothing was changed.$\r$\n$R2"
      ${EndIf}
    ${EndIf}
!macroend

!ifndef BUILD_UNINSTALLER

; ---------------------------------------------------------------- installer

Var nxTick
Var nxMoveSource
Var nxMoveTarget
Var nxMoveFlags
Var nxMoveSeconds
Var nxMoveResult
Var nxLayout   ; fresh | side | legacy
Var nxTarget   ; <install folder>\app-<version>
Var nxStaging  ; set only when the same version is reinstalled next to a complete copy
Var nxExtracted

Function nxNextTick
  System::Call 'kernel32::GetTickCount() i.s'
  Pop $nxTick
FunctionEnd

; MoveFileExW with retries; sets $nxMoveResult to 1 or 0. Security scanners can hold a file for minutes,
; so callers wait generously before reporting a failure.
Function nxMoveRetry
  Push $R4
  Push $R5
  loop:
    System::Call 'kernel32::MoveFileExW(w "$nxMoveSource", w "$nxMoveTarget", i $nxMoveFlags) i.R4 ?e'
    Pop $R5
    ${If} $R4 != 0
      StrCpy $nxMoveResult 1
      Goto done
    ${EndIf}
    ${If} $nxMoveSeconds <= 0
      !insertmacro nxLog "could not move $nxMoveSource to $nxMoveTarget (Windows error $R5)"
      StrCpy $nxMoveResult 0
      Goto done
    ${EndIf}
    IntOp $R4 $nxMoveSeconds % 10
    ${If} $R4 == 0
      !insertmacro nxLog "waiting for $nxMoveSource (Windows error $R5); $nxMoveSeconds s left"
    ${EndIf}
    Sleep 1000
    IntOp $nxMoveSeconds $nxMoveSeconds - 1
    Goto loop
  done:
  Pop $R5
  Pop $R4
FunctionEnd
!macro nxMove SOURCE DESTINATION FLAGS SECONDS RESULT
  StrCpy $nxMoveSource `${SOURCE}`
  StrCpy $nxMoveTarget `${DESTINATION}`
  StrCpy $nxMoveFlags ${FLAGS}
  StrCpy $nxMoveSeconds ${SECONDS}
  Call nxMoveRetry
  StrCpy ${RESULT} $nxMoveResult
!macroend

Function nxResolveLocation
  StrCpy $nxLog "$TEMP\nexusai-setup.log"
  ${GetParameters} $0
  !insertmacro nxLog "=== ${PRODUCT_NAME} ${VERSION} setup started; folder '$INSTDIR'; arguments '$0'"
  ; One installation per user: an existing one is always updated where it is.
  ReadRegStr $0 HKCU "Software\${APP_GUID}" InstallLocation
  ${If} $0 != ""
  ${AndIf} ${FileExists} "$0\*.*"
  ${AndIf} $0 != $INSTDIR
    ${If} ${Silent}
      !insertmacro nxLog "using the registered installation folder $0 instead of $INSTDIR"
    ${Else}
      MessageBox MB_OKCANCEL|MB_ICONINFORMATION "NexusAI is already installed in:$\r$\n$0$\r$\n$\r$\nThis version will be installed there, so you keep one copy and all your settings.$\r$\n$\r$\nTo move NexusAI to another folder or drive, uninstall it first (your data is kept), then run this installer again." IDOK nxUseRegistered
      !insertmacro nxFail 23 "Installation cancelled. NexusAI stays in $0."
      nxUseRegistered:
    ${EndIf}
    StrCpy $INSTDIR $0
  ${EndIf}
  Call nxCheckFolder
  ${If} ${FileExists} "$INSTDIR\${NX_POINTER}"
    StrCpy $nxLayout side
  ${ElseIf} ${FileExists} "$INSTDIR\resources\app.asar"
    StrCpy $nxLayout legacy
  ${Else}
    StrCpy $nxLayout fresh
  ${EndIf}
  !insertmacro nxLog "installation folder $INSTDIR; layout $nxLayout"
FunctionEnd

; Replaces electron-builder's check. Adding a version never touches running files, so the app may stay open;
; only the one-time conversion of an old single-folder installation needs it closed.
!macro customCheckAppRunning
  Call nxResolveLocation
  ${If} $nxLayout == legacy
    !insertmacro nxSafetyCheck install
  ${Else}
    !insertmacro nxSafetyCheck version
  ${EndIf}
!macroend

; Inserted (by installer-templates.cjs) where electron-builder would run the old uninstaller.
Function nxPrepare
  ; Never older than the version the launcher starts now.
  ReadINIStr $0 "$INSTDIR\${NX_POINTER}" "Install" "Current"
  ${If} $0 != ""
    ${VersionCompare} "$0" "${VERSION}" $1
    ${If} $1 == 1
      !insertmacro nxFail 12 "A newer NexusAI ($0) is already installed in $INSTDIR. Nothing was changed."
    ${EndIf}
  ${EndIf}

  ClearErrors
  CreateDirectory "$INSTDIR"
  FileOpen $0 "$INSTDIR\.nexusai-write-test" w
  ${If} ${Errors}
    !insertmacro nxFail 21 "NexusAI cannot write to $INSTDIR. Choose a folder you can write to, or ask IT for access."
  ${EndIf}
  FileClose $0
  Delete "$INSTDIR\.nexusai-write-test"

  ; The package is unpacked in the temporary folder, then copied into the version folder.
  !ifdef APP_64_UNPACKED_SIZE
    IntOp $2 ${APP_64_UNPACKED_SIZE} / 1024
    IntOp $2 $2 + 200
    ${GetRoot} "$INSTDIR" $3
    ${GetRoot} "$PLUGINSDIR" $4
    ${If} $3 == $4
      IntOp $5 $2 * 2
    ${Else}
      StrCpy $5 $2
      ${DriveSpace} "$4\" "/D=F /S=M" $6
      ${If} $6 < $2
        !insertmacro nxFail 22 "There is not enough free space for the temporary installation files on $4 ($6 MB free, $2 MB needed). Free some space and try again."
      ${EndIf}
    ${EndIf}
    ${DriveSpace} "$3\" "/D=F /S=M" $6
    ${If} $6 < $5
      !insertmacro nxFail 22 "There is not enough free space on $3 ($6 MB free, $5 MB needed). Free some space, or uninstall NexusAI and install it on another drive (your data is kept)."
    ${EndIf}
    !insertmacro nxLog "free space on $3: $6 MB; needed $5 MB"
  !endif

  StrCpy $nxTarget "$INSTDIR\app-${VERSION}"
  StrCpy $nxStaging ""
  StrCpy $nxExtracted $nxTarget
  ${If} ${FileExists} "$nxTarget\*.*"
    Call nxNextTick
    ${If} ${FileExists} "$nxTarget\${NX_COMPLETE}"
      ; Repair of the same version: unpack beside it, then swap if the old copy is not in use.
      StrCpy $nxStaging "$INSTDIR\.staging-${VERSION}-$nxTick"
      StrCpy $nxExtracted $nxStaging
      !insertmacro nxLog "reinstalling ${VERSION}: unpacking into $nxStaging"
    ${Else}
      ; Left over from an interrupted installation.
      !insertmacro nxMove "$nxTarget" "$INSTDIR\.trash-app-${VERSION}-$nxTick" ${NX_MOVE_PLAIN} 120 $0
      ${If} $0 != 1
        !insertmacro nxFail 32 "An unfinished copy of NexusAI ${VERSION} in $nxTarget is still in use by another program (often security scanning). Wait a few minutes and run the installer again. Nothing was changed."
      ${EndIf}
    ${EndIf}
  ${EndIf}
  !insertmacro nxLog "unpacking into $nxExtracted"
  SetOutPath "$nxExtracted"
FunctionEnd
!macro nxPrepareInstall
  Call nxPrepare
!macroend

; Copies a new launcher or uninstaller into the install folder and atomically replaces the old one.
; Sets $nxMoveResult to 1 or 0.
Var nxPlaceSource
Var nxPlaceName
Function nxPlaceRootFile
  Call nxNextTick
  ClearErrors
  CopyFiles /SILENT "$nxPlaceSource" "$INSTDIR\.$nxPlaceName.$nxTick.new"
  ${If} ${Errors}
    !insertmacro nxLog "could not copy $nxPlaceSource into $INSTDIR"
    StrCpy $nxMoveResult 0
  ${Else}
    !insertmacro nxMove "$INSTDIR\.$nxPlaceName.$nxTick.new" "$INSTDIR\$nxPlaceName" ${NX_MOVE_REPLACE} 60 $nxMoveResult
    ${If} $nxMoveResult != 1
      Delete "$INSTDIR\.$nxPlaceName.$nxTick.new"
    ${EndIf}
  ${EndIf}
FunctionEnd
!macro nxPlace SOURCE NAME RESULT
  StrCpy $nxPlaceSource `${SOURCE}`
  StrCpy $nxPlaceName `${NAME}`
  Call nxPlaceRootFile
  StrCpy ${RESULT} $nxMoveResult
!macroend

; Writes the old single-folder entries so the app removes exactly these later, once nothing holds them.
Function nxRecordLegacyFiles
  Push $0
  Push $1
  Push $2
  Push $3
  FileOpen $3 "$INSTDIR\.legacy-files" w
  FindFirst $0 $1 "$INSTDIR\*"
  loop:
    StrCmp $1 "" done
    StrCpy $2 $1 4
    ${If} $1 != "."
    ${AndIf} $1 != ".."
    ${AndIf} $2 != "app-"
    ${AndIf} $1 != "logs"
    ${AndIf} $1 != "${NX_POINTER}"
    ${AndIf} $1 != ".legacy-files"
    ${AndIf} $1 != "${NX_EXE}"
    ${AndIf} $1 != "${NX_UNINSTALLER}"
      StrCpy $2 $1 1
      ${If} $2 != "."
        FileWrite $3 "$1$\r$\n"
      ${EndIf}
    ${EndIf}
    FindNext $0 $1
    Goto loop
  done:
  FindClose $0
  FileClose $3
  Pop $3
  Pop $2
  Pop $1
  Pop $0
FunctionEnd

; Inserted (by installer-templates.cjs) after electron-builder unpacked the app.
Function nxActivate
  SetOutPath "$INSTDIR"
  ${IfNot} ${FileExists} "$nxExtracted\${NX_EXE}"
  ${OrIfNot} ${FileExists} "$nxExtracted\resources\app.asar"
  ${OrIfNot} ${FileExists} "$nxExtracted\${NX_LAUNCHER_SOURCE}"
  ${OrIfNot} ${FileExists} "$nxExtracted\${NX_UNINSTALLER}"
    RMDir /r "$nxExtracted"
    !insertmacro nxFail 31 "NexusAI's files were not unpacked completely (the disk may be full or a program removed files). Nothing was changed; try again."
  ${EndIf}
  ClearErrors
  FileOpen $0 "$nxExtracted\${NX_COMPLETE}" w
  FileWrite $0 "${VERSION}"
  FileClose $0
  ${If} ${Errors}
    RMDir /r "$nxExtracted"
    !insertmacro nxFail 31 "NexusAI could not finish writing its files to $nxExtracted. Nothing was changed; try again."
  ${EndIf}

  ${If} $nxStaging != ""
    Call nxNextTick
    !insertmacro nxMove "$nxTarget" "$INSTDIR\.trash-app-${VERSION}-$nxTick" ${NX_MOVE_PLAIN} 60 $0
    ${If} $0 == 1
      !insertmacro nxMove "$nxStaging" "$nxTarget" ${NX_MOVE_PLAIN} 60 $1
      ${If} $1 != 1
        !insertmacro nxMove "$INSTDIR\.trash-app-${VERSION}-$nxTick" "$nxTarget" ${NX_MOVE_PLAIN} 60 $0
        !insertmacro nxFail 32 "NexusAI ${VERSION} could not be repaired because its folder is in use. Close NexusAI, wait a few minutes and try again."
      ${EndIf}
    ${Else}
      ; The same version is in use (it is running): keep that complete copy.
      !insertmacro nxLog "the installed ${VERSION} is in use; keeping it and discarding the new copy"
      RMDir /r "$nxStaging"
    ${EndIf}
  ${EndIf}

  StrCpy $2 ""
  ${If} $nxLayout == legacy
    ; One-time conversion of an old single-folder installation (the app is closed: see customCheckAppRunning).
    Call nxRecordLegacyFiles
    Call nxNextTick
    StrCpy $2 "$INSTDIR\.trash-legacy-$nxTick"
    CreateDirectory "$2"
    ${If} ${FileExists} "$INSTDIR\${NX_EXE}"
      !insertmacro nxMove "$INSTDIR\${NX_EXE}" "$2\${NX_EXE}" ${NX_MOVE_PLAIN} 120 $0
      ${If} $0 != 1
        !insertmacro nxFail 35 "An old NexusAI program file in $INSTDIR is held by another program (often security scanning). Wait a few minutes and run the installer again. Your current version still works."
      ${EndIf}
    ${EndIf}
  ${EndIf}

  !insertmacro nxPlace "$nxTarget\${NX_LAUNCHER_SOURCE}" "${NX_EXE}" $0
  ${If} $0 != 1
    ${If} $nxLayout == side
      ; The current launcher reads the same pointer format, so it keeps working.
      !insertmacro nxLog "launcher not replaced (in use); the existing launcher stays"
    ${Else}
      ${If} $2 != ""
        ; Put the old program back so the existing shortcuts keep working.
        !insertmacro nxMove "$2\${NX_EXE}" "$INSTDIR\${NX_EXE}" ${NX_MOVE_PLAIN} 60 $0
      ${EndIf}
      !insertmacro nxFail 33 "NexusAI could not create its launcher in $INSTDIR (the file is in use or access is denied). Wait a few minutes and try again."
    ${EndIf}
  ${EndIf}
  !insertmacro nxPlace "$nxTarget\${NX_UNINSTALLER}" "${NX_UNINSTALLER}" $0
  ${If} $0 != 1
  ${AndIfNot} ${FileExists} "$INSTDIR\${NX_UNINSTALLER}"
    !insertmacro nxFail 33 "NexusAI could not create its uninstaller in $INSTDIR. Wait a few minutes and try again."
  ${EndIf}

  ; The switch: until this succeeds, the launcher keeps starting the previous version.
  Call nxNextTick
  ClearErrors
  FileOpen $0 "$INSTDIR\.${NX_POINTER}.$nxTick.new" w
  FileWrite $0 "[Install]$\r$\nFormat=1$\r$\nCurrent=${VERSION}$\r$\n"
  FileClose $0
  ${If} ${Errors}
    !insertmacro nxFail 34 "NexusAI could not record version ${VERSION} as active (cannot write in $INSTDIR). Run the installer again in a few minutes."
  ${EndIf}
  !insertmacro nxMove "$INSTDIR\.${NX_POINTER}.$nxTick.new" "$INSTDIR\${NX_POINTER}" ${NX_MOVE_REPLACE} 60 $0
  ${If} $0 != 1
    Delete "$INSTDIR\.${NX_POINTER}.$nxTick.new"
    ; The launcher falls back to the newest complete version, so a missing pointer still starts this one.
    !insertmacro nxFail 34 "NexusAI could not record version ${VERSION} as active because a file in $INSTDIR is in use. Run the installer again in a few minutes."
  ${EndIf}
  !insertmacro nxLog "version ${VERSION} is now active in $INSTDIR"
FunctionEnd
!macro nxActivateInstall
  Call nxActivate
!macroend

!else

; ---------------------------------------------------------------- uninstaller

Var nxDeleteData
Var nxDeleteBox

!macro customUnInit
  StrCpy $nxLog "$TEMP\nexusai-uninstall.log"
  ; Data is kept unless the user ticks the box (or a silent uninstall passes --delete-app-data).
  StrCpy $nxDeleteData 0
  ${if} ${isDeleteAppData}
    StrCpy $nxDeleteData 1
  ${endif}
  !insertmacro nxLog "=== ${PRODUCT_NAME} ${VERSION} uninstall started for '$INSTDIR'; delete data $nxDeleteData"
!macroend

; Inserted where electron-builder declares uninstaller pages, after MUI2 is loaded.
!macro customUnWelcomePage
  UninstPage custom un.nxDataPage un.nxDataPageLeave
Function un.nxDataPage
  !insertmacro MUI_HEADER_TEXT "Uninstall ${PRODUCT_NAME}" "Choose what happens to your data."
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 48u "${PRODUCT_NAME} will be removed from $INSTDIR.$\r$\n$\r$\nYour mail, settings, sign-ins and the contents NexusAI created in your Home folder are kept, so reinstalling continues where you left off."
  Pop $0
  ${NSD_CreateCheckbox} 0 60u 100% 12u "Also delete my NexusAI data from this computer"
  Pop $nxDeleteBox
  ${If} $nxDeleteData == 1
    ${NSD_Check} $nxDeleteBox
  ${EndIf}
  ${NSD_CreateLabel} 12u 76u 95% 30u "Deletes mail downloaded by NexusAI, settings, saved sign-ins and NexusAI's folders in your Home. Other files in your Home folder are not touched. This cannot be undone."
  Pop $0
  nsDialogs::Show
FunctionEnd

Function un.nxDataPageLeave
  ${NSD_GetState} $nxDeleteBox $0
  ${If} $0 == ${BST_CHECKED}
    MessageBox MB_YESNO|MB_ICONEXCLAMATION|MB_DEFBUTTON2 "Delete your NexusAI mail, settings and sign-ins from this computer? This cannot be undone." IDYES +2
    Abort
    StrCpy $nxDeleteData 1
  ${Else}
    StrCpy $nxDeleteData 0
  ${EndIf}
FunctionEnd
!macroend

!macro customCheckAppRunning
  StrCpy $nxLog "$TEMP\nexusai-uninstall.log"
  !insertmacro nxSafetyCheck uninstall
!macroend

!macro customUnInstall
  ${If} $nxDeleteData == 1
    InitPluginsDir
    File /oname=$PLUGINSDIR\nexusai-remove-data.ps1 "${PROJECT_DIR}\installer\remove-user-data.ps1"
    !insertmacro nxLog "deleting user data for ${NX_DATA_DIR}"
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\nexusai-remove-data.ps1" -DataDirectory "$APPDATA\${NX_DATA_DIR}" -LogFile "$nxLog"'
    Pop $0
    Pop $1
    ${If} $0 != 0
      !insertmacro nxLog "NX-52: data removal returned $0: $1"
      MessageBox MB_OK|MB_ICONEXCLAMATION "Some NexusAI data could not be deleted:$\r$\n$1$\r$\n$\r$\nError NX-52. Details: $nxLog" /SD IDOK
    ${EndIf}
  ${Else}
    !insertmacro nxLog "keeping user data in $APPDATA\${NX_DATA_DIR}"
  ${EndIf}
!macroend

; Replaces electron-builder's file removal, which gives up on the first locked file. Everything that can go
; goes; anything held by another program is reported and can be deleted later.
!macro customRemoveFiles
  Call un.nxCheckFolder
  ${If} ${FileExists} "$INSTDIR\${NX_POINTER}"
  ${OrIf} ${FileExists} "$INSTDIR\resources\app.asar"
    SetOutPath $TEMP
    StrCpy $1 30
    nxRemoveAgain:
      RMDir /r "$INSTDIR"
      ${If} ${FileExists} "$INSTDIR\*.*"
      ${AndIf} $1 > 0
        Sleep 1000
        IntOp $1 $1 - 1
        Goto nxRemoveAgain
      ${EndIf}
    ${If} ${FileExists} "$INSTDIR\*.*"
      !insertmacro nxLog "NX-51: some files in $INSTDIR are still in use"
      MessageBox MB_OK|MB_ICONINFORMATION "NexusAI was uninstalled, but some of its files are in use by another program (often security scanning) and could not be removed yet:$\r$\n$INSTDIR$\r$\n$\r$\nYou can delete this folder later.$\r$\n$\r$\nCode NX-51. Details: $nxLog" /SD IDOK
    ${Else}
      !insertmacro nxLog "removed $INSTDIR"
    ${EndIf}
  ${Else}
    !insertmacro nxLog "NX-51: $INSTDIR does not look like a NexusAI installation; its files were left in place"
  ${EndIf}
!macroend

!endif
