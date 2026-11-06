; NexusAI launcher: <install root>\<product>.exe. Shortcuts, pins and the uninstall entry point here.
; It starts <install root>\app-<version>\<product>.exe for the version named in nexusai-install.ini.
; Each version folder is complete only once the installer has written .nexusai-complete into it.
;
; Compile: makensis -DPRODUCT_EXE="NexusAI Beta.exe" -DPRODUCT_NAME="NexusAI Beta" -DICON=icon.ico -DOUTFILE=launcher.exe launcher.nsi
;
; Error codes (exit code, shown as NX-<code>):
;   40  no complete installed version was found
;   41  the app could not be started

Unicode true
SetCompressor /SOLID lzma
SilentInstall silent
RequestExecutionLevel user
ShowInstDetails nevershow
AutoCloseWindow true
Name "${PRODUCT_NAME}"
Caption "${PRODUCT_NAME}"
Icon "${ICON}"
OutFile "${OUTFILE}"
VIProductVersion "1.0.0.0"
VIAddVersionKey "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey "FileDescription" "${PRODUCT_NAME}"
VIAddVersionKey "FileVersion" "1.0.0.0"
VIAddVersionKey "LegalCopyright" "NexusAI"

!include LogicLib.nsh
!include FileFunc.nsh
!include WordFunc.nsh

!define POINTER "nexusai-install.ini"
!define COMPLETE ".nexusai-complete"
!define SYNCHRONIZE 0x00100000

Var version
Var logFile

Function log
  Exch $R9
  Push $R8
  ClearErrors
  CreateDirectory "$EXEDIR\logs"
  FileOpen $R8 "$logFile" a
  ${IfNot} ${Errors}
    FileSeek $R8 0 END
    FileWrite $R8 "launcher: $R9$\r$\n"
    FileClose $R8
  ${EndIf}
  Pop $R8
  Pop $R9
FunctionEnd
!macro log MESSAGE
  Push "${MESSAGE}"
  Call log
!macroend

; A version string from the pointer file must be digits and dots only; anything else could escape the folder.
Function isVersion
  Exch $R0
  Push $R1
  Push $R2
  StrCpy $R2 0
  ${If} $R0 == ""
    StrCpy $R0 0
    Goto done
  ${EndIf}
  loop:
    StrCpy $R1 $R0 1 $R2
    ${If} $R1 == ""
      StrCpy $R0 1
      Goto done
    ${EndIf}
    ${If} $R1 == "."
    ${OrIf} $R1 == "0"
    ${OrIf} $R1 == "1"
    ${OrIf} $R1 == "2"
    ${OrIf} $R1 == "3"
    ${OrIf} $R1 == "4"
    ${OrIf} $R1 == "5"
    ${OrIf} $R1 == "6"
    ${OrIf} $R1 == "7"
    ${OrIf} $R1 == "8"
    ${OrIf} $R1 == "9"
      IntOp $R2 $R2 + 1
      Goto loop
    ${EndIf}
    StrCpy $R0 0
  done:
  Pop $R2
  Pop $R1
  Exch $R0
FunctionEnd

Function isComplete
  Exch $R0
  ${If} ${FileExists} "$EXEDIR\app-$R0\${COMPLETE}"
  ${AndIf} ${FileExists} "$EXEDIR\app-$R0\${PRODUCT_EXE}"
    StrCpy $R0 1
  ${Else}
    StrCpy $R0 0
  ${EndIf}
  Exch $R0
FunctionEnd

; If the pointer is missing or names an unusable folder, fall back to the newest complete version.
Function newestComplete
  Push $R0
  Push $R1
  Push $R2
  Push $R3
  StrCpy $version ""
  FindFirst $R0 $R1 "$EXEDIR\app-*"
  loop:
    StrCmp $R1 "" done
    StrCpy $R2 $R1 "" 4
    Push $R2
    Call isVersion
    Pop $R3
    ${If} $R3 == 1
      Push $R2
      Call isComplete
      Pop $R3
      ${If} $R3 == 1
        ${If} $version == ""
          StrCpy $version $R2
        ${Else}
          ${VersionCompare} $R2 $version $R3
          ${If} $R3 == 1
            StrCpy $version $R2
          ${EndIf}
        ${EndIf}
      ${EndIf}
    ${EndIf}
    FindNext $R0 $R1
    Goto loop
  done:
  FindClose $R0
  Pop $R3
  Pop $R2
  Pop $R1
  Pop $R0
FunctionEnd

Section
  StrCpy $logFile "$EXEDIR\logs\launcher.log"
  ReadINIStr $version "$EXEDIR\${POINTER}" "Install" "Current"
  Push $version
  Call isVersion
  Pop $0
  ${If} $0 == 1
    Push $version
    Call isComplete
    Pop $0
  ${EndIf}
  ${If} $0 != 1
    !insertmacro log "pointer '$version' is not a complete version; looking for the newest complete one"
    Call newestComplete
  ${EndIf}
  ${If} $version == ""
    !insertmacro log "NX-40: no complete version in $EXEDIR"
    MessageBox MB_OK|MB_ICONSTOP "${PRODUCT_NAME} could not find its program files in $EXEDIR.$\r$\n$\r$\nRun the NexusAI installer again to repair it. Your data is not affected.$\r$\n$\r$\nError NX-40. Log: $logFile"
    SetErrorLevel 40
    Quit
  ${EndIf}

  ; A restart passes the old process ID so the new version only starts once the old one has exited.
  ${GetParameters} $1
  ${GetOptions} $1 "--wait-pid=" $2
  ${IfNot} ${Errors}
  ${AndIf} $2 != ""
    System::Call 'kernel32::OpenProcess(i ${SYNCHRONIZE}, i 0, i r2) p.r3'
    ${If} $3 P<> 0
      System::Call 'kernel32::WaitForSingleObject(p r3, i 60000) i.r4'
      System::Call 'kernel32::CloseHandle(p r3)'
      ${If} $4 != 0
        !insertmacro log "process $2 was still running after 60 s; starting anyway"
      ${EndIf}
    ${EndIf}
  ${EndIf}

  SetOutPath "$EXEDIR\app-$version"
  ClearErrors
  Exec '"$EXEDIR\app-$version\${PRODUCT_EXE}" $1'
  ${If} ${Errors}
    !insertmacro log "NX-41: could not start $EXEDIR\app-$version\${PRODUCT_EXE}"
    MessageBox MB_OK|MB_ICONSTOP "${PRODUCT_NAME} could not be started.$\r$\n$\r$\nRun the NexusAI installer again to repair it. Your data is not affected.$\r$\n$\r$\nError NX-41. Log: $logFile"
    SetErrorLevel 41
    Quit
  ${EndIf}
SectionEnd
