!include "getProcessInfo.nsh"

!macro customCheckAppRunning
  Var /GLOBAL nexusInstallerPid
  Var /GLOBAL nexusCheckResult
  Var /GLOBAL nexusCheckOutput
  ${GetProcessInfo} 0 $nexusInstallerPid $0 $1 $2 $3
  InitPluginsDir
  File /oname=$PLUGINSDIR\nexusai-check-install.ps1 "${PROJECT_DIR}\installer\check-install.ps1"
  !ifdef BUILD_UNINSTALLER
    !define NEXUS_CHECK_MODE "uninstall"
  !else
    !define NEXUS_CHECK_MODE "install"
  !endif
  nexusCheckAgain:
    DetailPrint "Waiting for NexusAI and its local services to close safely…"
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\nexusai-check-install.ps1" -InstallDirectory "$INSTDIR" -AppGuid "${APP_GUID}" -Version "${VERSION}" -InstallerProcessId $nexusInstallerPid -Mode ${NEXUS_CHECK_MODE} -LogFile "$TEMP\nexusai-installer-$nexusInstallerPid.log"'
    Pop $nexusCheckResult
    Pop $nexusCheckOutput
    ${If} $nexusCheckResult != 0
      DetailPrint "$nexusCheckOutput"
      ${If} $nexusCheckResult == 10
        MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$nexusCheckOutput$\r$\n$\r$\nLog: $TEMP\nexusai-installer-$nexusInstallerPid.log" /SD IDCANCEL IDRETRY nexusCheckAgain
      ${Else}
        MessageBox MB_OK|MB_ICONEXCLAMATION "$nexusCheckOutput$\r$\n$\r$\nInstaller safety check failed ($nexusCheckResult). No application files were replaced.$\r$\nLog: $TEMP\nexusai-installer-$nexusInstallerPid.log" /SD IDOK
      ${EndIf}
      SetErrorLevel 2
      Quit
    ${EndIf}
  !undef NEXUS_CHECK_MODE
!macroend
