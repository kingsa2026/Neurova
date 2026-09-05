Unicode true
ManifestDPIAware true
; Add in `dpiAwareness` `PerMonitorV2` to manifest for Windows 10 1607+ (note this should not affect lower versions since they should be able to ignore this and pick up `dpiAware` `true` set by `ManifestDPIAware true`)
; Currently undocumented on NSIS's website but is in the Docs folder of source tree, see
; https://github.com/kichik/nsis/blob/5fc0b87b819a9eec006df4967d08e522ddd651c9/Docs/src/attributes.but#L286-L300
; https://github.com/tauri-apps/tauri/pull/10106
ManifestDPIAwareness PerMonitorV2

!if "{{compression}}" == "none"
  SetCompress off
!else
  ; Set the compression algorithm. We default to LZMA.
  SetCompressor /SOLID "{{compression}}"
!endif

; Keep above !include to stay ahead of any plugin command
; see https://github.com/tauri-apps/tauri/pull/15422#discussion_r3289239624
{{#if signed_plugins_path}}
!addplugindir "{{signed_plugins_path}}"
{{/if}}

!include MUI2.nsh
!include FileFunc.nsh
!include x64.nsh
!include WordFunc.nsh
!include "utils.nsh"
!include "FileAssociation.nsh"
!include "Win\COM.nsh"
!include "Win\Propkey.nsh"
!include "StrFunc.nsh"
${StrCase}
${StrLoc}

{{#if installer_hooks}}
!include "{{installer_hooks}}"
{{/if}}

!define WEBVIEW2APPGUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

!define MANUFACTURER "{{manufacturer}}"
!define PRODUCTNAME "{{product_name}}"
!define VERSION "{{version}}"
!define VERSIONWITHBUILD "{{version_with_build}}"
!define HOMEPAGE "{{homepage}}"
!define TAGLINE "具备记忆、情感与自我进化的个人 AI 智能体"
!define INSTALLMODE "{{install_mode}}"
!define LICENSE "{{license}}"
!define INSTALLERICON "{{installer_icon}}"
!define SIDEBARIMAGE "{{sidebar_image}}"
!define HEADERIMAGE "{{header_image}}"
!define UNINSTALLERICON "{{uninstaller_icon}}"
!define UNINSTALLERHEADERIMAGE "{{uninstaller_header_image}}"
!define MAINBINARYNAME "{{main_binary_name}}"
!define MAINBINARYSRCPATH "{{main_binary_path}}"
!define BUNDLEID "{{bundle_id}}"
!define COPYRIGHT "{{copyright}}"
!define OUTFILE "{{out_file}}"
!define ARCH "{{arch}}"
!define ADDITIONALPLUGINSPATH "{{additional_plugins_path}}"
!define ALLOWDOWNGRADES "{{allow_downgrades}}"
!define DISPLAYLANGUAGESELECTOR "{{display_language_selector}}"
!define INSTALLWEBVIEW2MODE "{{install_webview2_mode}}"
!define WEBVIEW2INSTALLERARGS "{{webview2_installer_args}}"
!define WEBVIEW2BOOTSTRAPPERPATH "{{webview2_bootstrapper_path}}"
!define WEBVIEW2INSTALLERPATH "{{webview2_installer_path}}"
!define MINIMUMWEBVIEW2VERSION "{{minimum_webview2_version}}"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCTNAME}"
!define MANUKEY "Software\${MANUFACTURER}"
!define MANUPRODUCTKEY "${MANUKEY}\${PRODUCTNAME}"
!define UNINSTALLERSIGNCOMMAND "{{uninstaller_sign_cmd}}"
!define ESTIMATEDSIZE "{{estimated_size}}"
!define STARTMENUFOLDER "{{start_menu_folder}}"

Var PassiveMode
Var UpdateMode
Var NoShortcutMode
Var WixMode
Var OldMainBinaryName

; Neurova 首装管理员账号页（仅全新安装显示；写入 data/bootstrap_admin.ini 由后端首启消费）
Var AdminUsername
Var AdminPassword
Var AdminPassword2
Var AdminWritten

Name "${PRODUCTNAME}"
BrandingText "${COPYRIGHT}"
OutFile "${OUTFILE}"

; We don't actually use this value as default install path,
; it's just for nsis to append the product name folder in the directory selector
; https://nsis.sourceforge.io/Reference/InstallDir
!define PLACEHOLDER_INSTALL_DIR "placeholder\${PRODUCTNAME}"
InstallDir "${PLACEHOLDER_INSTALL_DIR}"

VIProductVersion "${VERSIONWITHBUILD}"
VIAddVersionKey "ProductName" "${PRODUCTNAME}"
VIAddVersionKey "FileDescription" "${PRODUCTNAME} Setup — AI Agent Desktop (智星)"
VIAddVersionKey "LegalCopyright" "${COPYRIGHT}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION} (${ARCH})"
VIAddVersionKey "CompanyName" "${MANUFACTURER}"
VIAddVersionKey "InternalName" "${PRODUCTNAME} Setup"
VIAddVersionKey "OriginalFilename" "${PRODUCTNAME}_${VERSION}_${ARCH}-setup.exe"
VIAddVersionKey "Comments" "${PRODUCTNAME} — ${TAGLINE}. Homepage: ${HOMEPAGE}"

# additional plugins
!addplugindir "${ADDITIONALPLUGINSPATH}"

; Uninstaller signing command
!if "${UNINSTALLERSIGNCOMMAND}" != ""
  !uninstfinalize '${UNINSTALLERSIGNCOMMAND}'
!endif

; Handle install mode, `perUser`, `perMachine` or `both`
!if "${INSTALLMODE}" == "perMachine"
  RequestExecutionLevel admin
!endif

!if "${INSTALLMODE}" == "currentUser"
  RequestExecutionLevel user
!endif

!if "${INSTALLMODE}" == "both"
  !define MULTIUSER_MUI
  !define MULTIUSER_INSTALLMODE_INSTDIR "${PRODUCTNAME}"
  !define MULTIUSER_INSTALLMODE_COMMANDLINE
  !if "${ARCH}" == "x64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !else if "${ARCH}" == "arm64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !endif
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_KEY "${UNINSTKEY}"
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "CurrentUser"
  !define MULTIUSER_INSTALLMODEPAGE_SHOWUSERNAME
  !define MULTIUSER_INSTALLMODE_FUNCTION RestorePreviousInstallLocation
  !define MULTIUSER_EXECUTIONLEVEL Highest
  !include MultiUser.nsh
!endif

; Installer icon
!if "${INSTALLERICON}" != ""
  !define MUI_ICON "${INSTALLERICON}"
!endif

; Installer sidebar image
!if "${SIDEBARIMAGE}" != ""
  !define MUI_WELCOMEFINISHPAGE_BITMAP "${SIDEBARIMAGE}"
!endif

; Enable header images for installer and uninstaller pages when either image is configured.
!if "${HEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE
!else if "${UNINSTALLERHEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE
!endif

; Installer header image
!if "${HEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE_BITMAP "${HEADERIMAGE}"
  ; 保高不变形：默认 FitControl 会把 150x57 横向拉满整条标题栏
  !define MUI_HEADERIMAGE_BITMAP_STRETCH "AspectFitHeight"
!endif

; Uninstaller header image
!if "${UNINSTALLERHEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE_UNBITMAP "${UNINSTALLERHEADERIMAGE}"
  !define MUI_HEADERIMAGE_UNBITMAP_STRETCH "AspectFitHeight"
!endif

; Uninstaller icon
!if "${UNINSTALLERICON}" != ""
  !define MUI_UNICON "${UNINSTALLERICON}"
!endif

; Define registry key to store installer language
!define MUI_LANGDLL_REGISTRY_ROOT "HKCU"
!define MUI_LANGDLL_REGISTRY_KEY "${MANUPRODUCTKEY}"
!define MUI_LANGDLL_REGISTRY_VALUENAME "Installer Language"

; Neurova：欢迎/完成页品牌配色（与启动进度窗 #1A2148 同色系）
; NSIS SetCtlColors 颜色字面量为 RRGGBB（红在前）——此前按 BBGGRR 误写
; 0x48211A，实际渲染成 RGB(72,33,26) 咖啡棕（用户截图证实）。
!define MUI_BGCOLOR "1A2148"
!define MUI_TEXTCOLOR "F2F5FF"
; 安装进度页同色系：深靛蓝底 + 浅色日志文字（统一整体风格）
!define MUI_INSTFILESPAGE_COLORS "F2F5FF 1A2148"
; 注意：LangString 必须在 MUI_LANGUAGE 之后定义（LANG_* 常量届时才存在），
; 全部自定义文案统一放下方「语言块之后」区域。
!define MUI_FINISHPAGE_TITLE "$(nsFinishTitle)"
!define MUI_FINISHPAGE_TEXT "$(nsFinishText)"

; Installer pages, must be ordered as they appear
; 1. 单页自定义安装器（Hero 品牌图 + 协议勾选 + 安装位置 + 一键安装）
;    替代 MUI 欢迎页/许可页/目录页三段式（Driver Booster 式单页交互）
Var FastInstall        ; 1=一键安装（跳过目录页） 0=自定义安装（走目录页）
Var hCustDlg           ; 自定义页对话框句柄
Var hHeroBitmap
Var hEulaCheck
Var hEulaLink
Var hPathText
Var hBtnInstall
Page custom PageWelcome PageLeaveWelcome

; 2. Install mode (if it is set to `both`)
!if "${INSTALLMODE}" == "both"
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !insertmacro MULTIUSER_PAGE_INSTALLMODE
!endif

; 4. Custom page to ask user if he wants to reinstall/uninstall
;    only if a previous installation was detected
Var ReinstallPageCheck
Page custom PageReinstall PageLeaveReinstall
Function PageReinstall
  ; Uninstall previous WiX installation if exists.
  ;
  ; A WiX installer stores the installation info in registry
  ; using a UUID and so we have to loop through all keys under
  ; `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall`
  ; and check if `DisplayName` and `Publisher` keys match ${PRODUCTNAME} and ${MANUFACTURER}
  ;
  ; This has a potential issue that there maybe another installation that matches
  ; our ${PRODUCTNAME} and ${MANUFACTURER} but wasn't installed by our WiX installer,
  ; however, this should be fine since the user will have to confirm the uninstallation
  ; and they can chose to abort it if doesn't make sense.
  StrCpy $0 0
  wix_loop:
    EnumRegKey $1 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" $0
    StrCmp $1 "" wix_loop_done ; Exit loop if there is no more keys to loop on
    IntOp $0 $0 + 1
    ReadRegStr $R0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "DisplayName"
    ReadRegStr $R1 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "Publisher"
    StrCmp "$R0$R1" "${PRODUCTNAME}${MANUFACTURER}" 0 wix_loop
    ReadRegStr $R0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "UninstallString"
    ${StrCase} $R1 $R0 "L"
    ${StrLoc} $R0 $R1 "msiexec" ">"
    StrCmp $R0 0 0 wix_loop_done
    StrCpy $WixMode 1
    StrCpy $R6 "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1"
    Goto compare_version
  wix_loop_done:

  ; Check if there is an existing installation, if not, abort the reinstall page
  ReadRegStr $R0 SHCTX "${UNINSTKEY}" ""
  ReadRegStr $R1 SHCTX "${UNINSTKEY}" "UninstallString"
  ${IfThen} "$R0$R1" == "" ${|} Abort ${|}

  ; Compare this installar version with the existing installation
  ; and modify the messages presented to the user accordingly
  compare_version:
  StrCpy $R4 "$(older)"
  ${If} $WixMode = 1
    ReadRegStr $R0 HKLM "$R6" "DisplayVersion"
  ${Else}
    ReadRegStr $R0 SHCTX "${UNINSTKEY}" "DisplayVersion"
  ${EndIf}
  ${IfThen} $R0 == "" ${|} StrCpy $R4 "$(unknown)" ${|}

  nsis_tauri_utils::SemverCompare "${VERSION}" $R0
  Pop $R0
  ; Reinstalling the same version
  ${If} $R0 = 0
    StrCpy $R1 "$(alreadyInstalledLong)"
    StrCpy $R2 "$(addOrReinstall)"
    StrCpy $R3 "$(uninstallApp)"
    !insertmacro MUI_HEADER_TEXT "$(alreadyInstalled)" "$(chooseMaintenanceOption)"
  ; Upgrading
  ${ElseIf} $R0 = 1
    StrCpy $R1 "$(olderOrUnknownVersionInstalled)"
    StrCpy $R2 "$(uninstallBeforeInstalling)"
    StrCpy $R3 "$(dontUninstall)"
    !insertmacro MUI_HEADER_TEXT "$(alreadyInstalled)" "$(choowHowToInstall)"
  ; Downgrading
  ${ElseIf} $R0 = -1
    StrCpy $R1 "$(newerVersionInstalled)"
    StrCpy $R2 "$(uninstallBeforeInstalling)"
    !if "${ALLOWDOWNGRADES}" == "true"
      StrCpy $R3 "$(dontUninstall)"
    !else
      StrCpy $R3 "$(dontUninstallDowngrade)"
    !endif
    !insertmacro MUI_HEADER_TEXT "$(alreadyInstalled)" "$(choowHowToInstall)"
  ${Else}
    Abort
  ${EndIf}

  ; Skip showing the page if passive
  ;
  ; Note that we don't call this earlier at the begining
  ; of this function because we need to populate some variables
  ; related to current installed version if detected and whether
  ; we are downgrading or not.
  ${If} $PassiveMode = 1
    Call PageLeaveReinstall
  ${Else}
    nsDialogs::Create 1018
    Pop $R4
    ${IfThen} $(^RTL) = 1 ${|} nsDialogs::SetRTL $(^RTL) ${|}

    ${NSD_CreateLabel} 0 0 100% 24u $R1
    Pop $R1

    ${NSD_CreateRadioButton} 30u 50u -30u 8u $R2
    Pop $R2
    ${NSD_OnClick} $R2 PageReinstallUpdateSelection

    ${NSD_CreateRadioButton} 30u 70u -30u 8u $R3
    Pop $R3
    ; Disable this radio button if downgrading and downgrades are disabled
    !if "${ALLOWDOWNGRADES}" == "false"
      ${IfThen} $R0 = -1 ${|} EnableWindow $R3 0 ${|}
    !endif
    ${NSD_OnClick} $R3 PageReinstallUpdateSelection

    ; Check the first radio button if this the first time
    ; we enter this page or if the second button wasn't
    ; selected the last time we were on this page
    ${If} $ReinstallPageCheck <> 2
      SendMessage $R2 ${BM_SETCHECK} ${BST_CHECKED} 0
    ${Else}
      SendMessage $R3 ${BM_SETCHECK} ${BST_CHECKED} 0
    ${EndIf}

    ${NSD_SetFocus} $R2
    nsDialogs::Show
  ${EndIf}
FunctionEnd
Function PageReinstallUpdateSelection
  ${NSD_GetState} $R2 $R1
  ${If} $R1 == ${BST_CHECKED}
    StrCpy $ReinstallPageCheck 1
  ${Else}
    StrCpy $ReinstallPageCheck 2
  ${EndIf}
FunctionEnd
Function PageLeaveReinstall
  ${NSD_GetState} $R2 $R1

  ; If migrating from Wix, always uninstall
  ${If} $WixMode = 1
    Goto reinst_uninstall
  ${EndIf}

  ; In update mode, always proceeds without uninstalling
  ${If} $UpdateMode = 1
    Goto reinst_done
  ${EndIf}

  ; $R0 holds whether same(0)/upgrading(1)/downgrading(-1) version
  ; $R1 holds the radio buttons state:
  ;   1 => first choice was selected
  ;   0 => second choice was selected
  ${If} $R0 = 0 ; Same version, proceed
    ${If} $R1 = 1              ; User chose to add/reinstall
      Goto reinst_done
    ${Else}                    ; User chose to uninstall
      Goto reinst_uninstall
    ${EndIf}
  ${ElseIf} $R0 = 1 ; Upgrading
    ${If} $R1 = 1              ; User chose to uninstall
      Goto reinst_uninstall
    ${Else}
      Goto reinst_done         ; User chose NOT to uninstall
    ${EndIf}
  ${ElseIf} $R0 = -1 ; Downgrading
    ${If} $R1 = 1              ; User chose to uninstall
      Goto reinst_uninstall
    ${Else}
      Goto reinst_done         ; User chose NOT to uninstall
    ${EndIf}
  ${EndIf}

  reinst_uninstall:
    HideWindow
    ClearErrors

    ${If} $WixMode = 1
      ReadRegStr $R1 HKLM "$R6" "UninstallString"
      ExecWait '$R1' $0
    ${Else}
      ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
      ReadRegStr $R1 SHCTX "${UNINSTKEY}" "UninstallString"
      ${IfThen} $UpdateMode = 1 ${|} StrCpy $R1 "$R1 /UPDATE" ${|} ; append /UPDATE
      ${IfThen} $PassiveMode = 1 ${|} StrCpy $R1 "$R1 /P" ${|} ; append /P
      StrCpy $R1 "$R1 _?=$4" ; append uninstall directory
      ExecWait '$R1' $0
    ${EndIf}

    BringToFront

    ${IfThen} ${Errors} ${|} StrCpy $0 2 ${|} ; ExecWait failed, set fake exit code

    ${If} $0 <> 0
    ${OrIf} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
      ; User cancelled wix uninstaller? return to select un/reinstall page
      ${If} $WixMode = 1
      ${AndIf} $0 = 1602
        Abort
      ${EndIf}

      ; User cancelled NSIS uninstaller? return to select un/reinstall page
      ${If} $0 = 1
        Abort
      ${EndIf}

      ; Other erros? show generic error message and return to select un/reinstall page
      MessageBox MB_ICONEXCLAMATION "$(unableToUninstall)"
      Abort
    ${EndIf}
  reinst_done:
FunctionEnd

; 5. Neurova 首装管理员账号页（仅全新安装；升级时 Abort 跳过）
Page custom PageAdminAccount PageLeaveAdminAccount

Function PageAdminAccount
  ; 升级/重装场景（检测到既有安装注册表项）→ 不显示。
  ; 双查 HKLM（perMachine 本版/历史）+ HKCU（早期 currentUser 旧版安装）：
  ; 否则 currentUser→perMachine 升级会误判为全新安装、重复索要账号。
  ReadRegStr $R0 SHCTX "${UNINSTKEY}" ""
  ReadRegStr $R1 SHCTX "${UNINSTKEY}" "UninstallString"
  ReadRegStr $R2 HKCU "${UNINSTKEY}" ""
  ReadRegStr $R3 HKCU "${UNINSTKEY}" "UninstallString"
  ${IfThen} "$R0$R1$R2$R3" != "" ${|} Abort ${|}
  ${IfThen} $PassiveMode = 1 ${|} Abort ${|}

  !insertmacro MUI_HEADER_TEXT "$(adminPageTitle)" "$(adminPageSubtitle)"

  StrCpy $AdminUsername ""
  StrCpy $AdminPassword ""
  StrCpy $AdminPassword2 ""

  nsDialogs::Create 1018
  Pop $R4
  ${IfThen} $(^RTL) = 1 ${|} nsDialogs::SetRTL $(^RTL) ${|}

  ; 品牌强调条（主色 #4D6BFE 细线，与单页主界面统一）
  ${NSD_CreateLabel} 0 0 100% 3u ""
  Pop $R0
  SetCtlColors $R0 "" 0x4D6BFE

  ${NSD_CreateLabel} 0 14u 100% 8u "$(adminUsernameLabel)"
  Pop $R0
  SetCtlColors $R0 0x1A2148 transparent
  ${NSD_CreateText} 0 24u 100% 12u ""
  Pop $AdminUsername

  ${NSD_CreateLabel} 0 42u 100% 8u "$(adminPasswordLabel)"
  Pop $R0
  SetCtlColors $R0 0x1A2148 transparent
  ${NSD_CreatePassword} 0 52u 100% 12u ""
  Pop $AdminPassword

  ${NSD_CreateLabel} 0 70u 100% 8u "$(adminPassword2Label)"
  Pop $R0
  SetCtlColors $R0 0x1A2148 transparent
  ${NSD_CreatePassword} 0 80u 100% 12u ""
  Pop $AdminPassword2

  ${NSD_CreateLabel} 0 98u 100% 16u "$(adminPageHint)"
  Pop $R0
  SetCtlColors $R0 0x8A93A8 transparent

  ${NSD_SetFocus} $AdminUsername
  nsDialogs::Show
FunctionEnd

Function PageLeaveAdminAccount
  ${NSD_GetText} $AdminUsername $R0
  ${NSD_GetText} $AdminPassword $R1
  ${NSD_GetText} $AdminPassword2 $R2

  ; 用户名为空 → 拦截
  ${If} "$R0" == ""
    MessageBox MB_ICONEXCLAMATION "$(adminInvalidUsername)"
    Abort
  ${EndIf}

  ; 合法字符集校验（黑名单扫描）
  Push "$R0"
  Call ValidateAdminUsername
  Pop $R3
  ${If} "$R3" != "1"
    MessageBox MB_ICONEXCLAMATION "$(adminInvalidUsername)"
    Abort
  ${EndIf}

  ; 密码为空或两次不一致 → 拦截（S!= = 大小写敏感比较；LogicLib 的 != 不分
  ; 大小写，"Pass123" 与 "pass123" 会被误判一致）
  ${If} "$R1" == ""
    MessageBox MB_ICONEXCLAMATION "$(adminInvalidPassword)"
    Abort
  ${EndIf}
  ${If} "$R1" S!= "$R2"
    MessageBox MB_ICONEXCLAMATION "$(adminPasswordMismatch)"
    Abort
  ${EndIf}

  ; 暂存到 Var（Section Install 里 WriteINIStr）
  StrCpy $AdminUsername "$R0"
  StrCpy $AdminPassword "$R1"
  StrCpy $AdminWritten "1"
FunctionEnd

; 合法用户名 = 仅字母/数字/_-/.，长度 1..32（黑名单扫描：空格、引号、
; 冒号、斜杠、反斜杠、尖括号、竖线、问号、星号、百分号、制表符）
; 结果入栈："1" 合法 / "0" 非法
Function ValidateAdminUsername
  Exch $R9          ; 入参：用户名
  Push $R8
  Push $R7
  Push $R6
  Push $R5

  StrCpy $R6 "1"
  StrLen $R8 "$R9"
  ${If} $R8 < 1
  ${OrIf} $R8 > 32
    StrCpy $R6 "0"
    Goto validate_done
  ${EndIf}

  StrCpy $R7 0
  ${While} $R7 < $R8
    StrCpy $R5 "$R9" 1 $R7
    ${If} "$R5" == " "
    ${OrIf} "$R5" == "$\t"
    ${OrIf} "$R5" == "$\""
    ${OrIf} "$R5" == ":"
    ${OrIf} "$R5" == "/"
    ${OrIf} "$R5" == "\"
    ${OrIf} "$R5" == "<"
    ${OrIf} "$R5" == ">"
    ${OrIf} "$R5" == "|"
    ${OrIf} "$R5" == "?"
    ${OrIf} "$R5" == "*"
    ${OrIf} "$R5" == "%"
    ${OrIf} "$R5" == "$$"
      StrCpy $R6 "0"
      Goto validate_done
    ${EndIf}
    IntOp $R7 $R7 + 1
  ${EndWhile}

  validate_done:
  StrCpy $R9 "$R6"
  Pop $R5
  Pop $R6
  Pop $R7
  Pop $R8
  Exch $R9
FunctionEnd

; 6. Choose install directory page（一键安装模式下跳过——主页面已显示目标位置）
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipDirIfFastOrPassive
!insertmacro MUI_PAGE_DIRECTORY
; 6. Start menu shortcut page
Var AppStartMenuFolder
!if "${STARTMENUFOLDER}" != ""
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !define MUI_STARTMENUPAGE_DEFAULTFOLDER "${STARTMENUFOLDER}"
!else
  !define MUI_PAGE_CUSTOMFUNCTION_PRE Skip
!endif
!insertmacro MUI_PAGE_STARTMENU Application $AppStartMenuFolder

; 7. Installation page
!insertmacro MUI_PAGE_INSTFILES

; 8. Finish page
;
; Don't auto jump to finish page after installation page,
; because the installation page has useful info that can be used debug any issues with the installer.
!define MUI_FINISHPAGE_NOAUTOCLOSE
; Neurova：完成页唯一勾选位 =「开机自动启动」（默认不勾）；
; 桌面快捷方式改为安装时恒建（见 Section Install 尾部）。
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "$(autostart)"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION SetAutostartEntry
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
; Show run app after installation.
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION RunMainBinary
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_FINISH

Function RunMainBinary
  nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
FunctionEnd

; 开机自启 = HKCU Run 键（卸载时模板原有逻辑会清 HKCU Run）
Function SetAutostartEntry
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${PRODUCTNAME}" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\""
FunctionEnd

; Uninstaller Pages
; 1. Confirm uninstall page
Var DeleteAppDataCheckbox
Var DeleteAppDataCheckboxState
!define /ifndef WS_EX_LAYOUTRTL         0x00400000
!define MUI_PAGE_CUSTOMFUNCTION_SHOW un.ConfirmShow
Function un.ConfirmShow ; Add add a `Delete app data` check box
  ; $1 inner dialog HWND
  ; $2 window DPI
  ; $3 style
  ; $4 x
  ; $5 y
  ; $6 width
  ; $7 height
  FindWindow $1 "#32770" "" $HWNDPARENT ; Find inner dialog
  System::Call "user32::GetDpiForWindow(p r1) i .r2"
  ${If} $(^RTL) = 1
    StrCpy $3 "${__NSD_CheckBox_EXSTYLE} | ${WS_EX_LAYOUTRTL}"
    IntOp $4 50 * $2
  ${Else}
    StrCpy $3 "${__NSD_CheckBox_EXSTYLE}"
    IntOp $4 0 * $2
  ${EndIf}
  IntOp $5 100 * $2
  IntOp $6 400 * $2
  IntOp $7 25 * $2
  IntOp $4 $4 / 96
  IntOp $5 $5 / 96
  IntOp $6 $6 / 96
  IntOp $7 $7 / 96
  System::Call 'user32::CreateWindowEx(i r3, w "${__NSD_CheckBox_CLASS}", w "$(nsDeleteData)", i ${__NSD_CheckBox_STYLE}, i r4, i r5, i r6, i r7, p r1, i0, i0, i0) i .s'
  Pop $DeleteAppDataCheckbox
  SendMessage $HWNDPARENT ${WM_GETFONT} 0 0 $1
  SendMessage $DeleteAppDataCheckbox ${WM_SETFONT} $1 1
FunctionEnd
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE un.ConfirmLeave
Function un.ConfirmLeave
  SendMessage $DeleteAppDataCheckbox ${BM_GETCHECK} 0 0 $DeleteAppDataCheckboxState
FunctionEnd
!define MUI_PAGE_CUSTOMFUNCTION_PRE un.SkipIfPassive
!insertmacro MUI_UNPAGE_CONFIRM

; 2. Uninstalling Page
!insertmacro MUI_UNPAGE_INSTFILES

;Languages
{{#each languages}}
!insertmacro MUI_LANGUAGE "{{this}}"
{{/each}}
!insertmacro MUI_RESERVEFILE_LANGDLL
{{#each language_files}}
  !include "{{this}}"
{{/each}}

; Neurova 自定义文案（放在 MUI_LANGUAGE 之后：LANG_* 常量届时才存在）
LangString nsWelcomeTitle ${LANG_ENGLISH} "Welcome to Neurova"
LangString nsWelcomeTitle ${LANG_SIMPCHINESE} "欢迎使用 Neurova 智星"
; 单页安装器标签（Hero 图内已烙介绍与地址，无需 nsWelcomeText）
LangString nsEulaPre ${LANG_ENGLISH} "I have read and agree to the"
LangString nsEulaPre ${LANG_SIMPCHINESE} "我已阅读并同意"
LangString nsEulaLink ${LANG_ENGLISH} "License Agreement"
LangString nsEulaLink ${LANG_SIMPCHINESE} "《软件许可协议》"
LangString nsEulaWarn ${LANG_ENGLISH} "Please read and accept the license agreement first."
LangString nsEulaWarn ${LANG_SIMPCHINESE} "请先阅读并勾选同意《软件许可协议》。"
LangString nsPathLabel ${LANG_ENGLISH} "Install to:"
LangString nsPathLabel ${LANG_SIMPCHINESE} "安装位置："
LangString nsCustomInstall ${LANG_ENGLISH} "Custom Install"
LangString nsCustomInstall ${LANG_SIMPCHINESE} "自定义安装"
LangString nsInstallBtn ${LANG_ENGLISH} "Install Now"
LangString nsInstallBtn ${LANG_SIMPCHINESE} "一键安装"
LangString nsFinishTitle ${LANG_ENGLISH} "Neurova Installation Complete"
LangString nsFinishTitle ${LANG_SIMPCHINESE} "Neurova 智星 安装完成"
LangString nsFinishText ${LANG_ENGLISH} "Setup has finished installing Neurova on your computer.$\r$\n$\r$\nWebsite: www.neurova.top$\r$\nGitHub:  github.com/kingsa2026/Neurova$\r$\n$\r$\nClick Finish to close this wizard."
LangString nsFinishText ${LANG_SIMPCHINESE} "Neurova 智星 已成功安装到您的电脑。$\r$\n$\r$\n官方网站： www.neurova.top$\r$\n开源地址： github.com/kingsa2026/Neurova$\r$\n$\r$\n点击“完成”关闭本向导。"
; Neurova 首装管理员账号页文案（SimpChinese + English；其他语言回退 English）
LangString adminPageTitle        ${LANG_ENGLISH} "Create Admin Account"
LangString adminPageSubtitle     ${LANG_ENGLISH} "This is the first account and will have administrator privileges"
LangString adminUsernameLabel    ${LANG_ENGLISH} "Username:"
LangString adminPasswordLabel    ${LANG_ENGLISH} "Password:"
LangString adminPassword2Label   ${LANG_ENGLISH} "Confirm password:"
LangString adminPageHint         ${LANG_ENGLISH} "You will use this account to log in to Neurova. Remember your password."
LangString adminInvalidUsername  ${LANG_ENGLISH} "Invalid username: 1-32 characters, no spaces or special characters ( : \\ / < > | ? * % quotes )"
LangString adminInvalidPassword  ${LANG_ENGLISH} "Password cannot be empty"
LangString adminPasswordMismatch ${LANG_ENGLISH} "Passwords do not match"

LangString adminPageTitle        ${LANG_SIMPCHINESE} "创建管理员账号"
LangString adminPageSubtitle     ${LANG_SIMPCHINESE} "这是系统的第一个账号，将拥有管理员权限"
LangString adminUsernameLabel    ${LANG_SIMPCHINESE} "用户名："
LangString adminPasswordLabel    ${LANG_SIMPCHINESE} "密码："
LangString adminPassword2Label   ${LANG_SIMPCHINESE} "确认密码："
LangString adminPageHint         ${LANG_SIMPCHINESE} "此账号用于登录 Neurova，请牢记密码。"
LangString adminInvalidUsername  ${LANG_SIMPCHINESE} "用户名无效：1-32 个字符，不能含空格或特殊字符（: \\ / < > | ? * % 引号）"
LangString adminInvalidPassword  ${LANG_SIMPCHINESE} "密码不能为空"
LangString adminPasswordMismatch ${LANG_SIMPCHINESE} "两次输入的密码不一致"

; Neurova 卸载数据策略 + 完成页自启（双语）
LangString nsDeleteData ${LANG_ENGLISH} "Delete ALL my data (agent memory, skills, chat history, config — cannot be undone)"
LangString nsDeleteData ${LANG_SIMPCHINESE} "彻底删除我的全部数据（Agent 记忆/技能/聊天记录/配置，不可恢复）"
LangString autostart ${LANG_ENGLISH} "Start Neurova automatically when Windows starts"
LangString autostart ${LANG_SIMPCHINESE} "开机自动启动 Neurova"

Function .onInit
  ; Neurova：账号页凭据标志（仅 PageLeaveAdminAccount 置 1）
  StrCpy $AdminWritten "0"

  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}

  ${GetOptions} $CMDLINE "/NS" $NoShortcutMode
  ${IfNot} ${Errors}
    StrCpy $NoShortcutMode 1
  ${EndIf}

  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}

  !if "${DISPLAYLANGUAGESELECTOR}" == "true"
    !insertmacro MUI_LANGDLL_DISPLAY
  !endif

  !insertmacro SetContext

  ${If} $INSTDIR == "${PLACEHOLDER_INSTALL_DIR}"
    ; Set default install location
    ; Neurova 定制：默认安装到 D:\Program Files（产品需求）。
    ; 升级场景仍由 RestorePreviousInstallLocation 用注册表记录的旧目录覆盖。
    !if "${INSTALLMODE}" == "perMachine"
      ${If} ${RunningX64}
        !if "${ARCH}" == "x64"
          StrCpy $INSTDIR "D:\Program Files\${PRODUCTNAME}"
        !else if "${ARCH}" == "arm64"
          StrCpy $INSTDIR "D:\Program Files\${PRODUCTNAME}"
        !else
          StrCpy $INSTDIR "D:\Program Files\${PRODUCTNAME}"
        !endif
      ${Else}
        StrCpy $INSTDIR "D:\Program Files\${PRODUCTNAME}"
      ${EndIf}
    !else if "${INSTALLMODE}" == "currentUser"
      StrCpy $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}"
    !endif

    Call RestorePreviousInstallLocation
  ${EndIf}


  !if "${INSTALLMODE}" == "both"
    !insertmacro MULTIUSER_INIT
  !endif
FunctionEnd


Section EarlyChecks
  ; Abort silent installer if downgrades is disabled
  !if "${ALLOWDOWNGRADES}" == "false"
  ${If} ${Silent}
    ; If downgrading
    ${If} $R0 = -1
      System::Call 'kernel32::AttachConsole(i -1)i.r0'
      ${If} $0 <> 0
        System::Call 'kernel32::GetStdHandle(i -11)i.r0'
        System::call 'kernel32::SetConsoleTextAttribute(i r0, i 0x0004)' ; set red color
        FileWrite $0 "$(silentDowngrades)"
      ${EndIf}
      Abort
    ${EndIf}
  ${EndIf}
  !endif

SectionEnd

Section WebView2
  ; Check if Webview2 is already installed and skip this section
  ${If} ${RunningX64}
    ReadRegStr $4 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${Else}
    ReadRegStr $4 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}
  ${If} $4 == ""
    ReadRegStr $4 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}

  ${If} $4 == ""
    ; Webview2 installation
    ;
    ; Skip if updating
    ${If} $UpdateMode <> 1
      !if "${INSTALLWEBVIEW2MODE}" == "downloadBootstrapper"
        Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        DetailPrint "$(webview2Downloading)"
        NSISdl::download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Pop $0
        ${If} $0 == "success"
          DetailPrint "$(webview2DownloadSuccess)"
        ${Else}
          DetailPrint "$(webview2DownloadError)"
          Abort "$(webview2AbortError)"
        ${EndIf}
        StrCpy $6 "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Goto install_webview2
      !endif

      !if "${INSTALLWEBVIEW2MODE}" == "embedBootstrapper"
        Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        File "/oname=$TEMP\MicrosoftEdgeWebview2Setup.exe" "${WEBVIEW2BOOTSTRAPPERPATH}"
        DetailPrint "$(installingWebview2)"
        StrCpy $6 "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Goto install_webview2
      !endif

      !if "${INSTALLWEBVIEW2MODE}" == "offlineInstaller"
        Delete "$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe"
        File "/oname=$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe" "${WEBVIEW2INSTALLERPATH}"
        DetailPrint "$(installingWebview2)"
        StrCpy $6 "$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe"
        Goto install_webview2
      !endif

      Goto webview2_done

      install_webview2:
        DetailPrint "$(installingWebview2)"
        ; $6 holds the path to the webview2 installer
        ExecWait "$6 ${WEBVIEW2INSTALLERARGS} /install" $1
        ${If} $1 = 0
          DetailPrint "$(webview2InstallSuccess)"
        ${Else}
          DetailPrint "$(webview2InstallError)"
          Abort "$(webview2AbortError)"
        ${EndIf}
      webview2_done:
    ${EndIf}
  ${Else}
    !if "${MINIMUMWEBVIEW2VERSION}" != ""
      ${VersionCompare} "${MINIMUMWEBVIEW2VERSION}" "$4" $R0
      ${If} $R0 = 1
        update_webview:
          DetailPrint "$(installingWebview2)"
          ${If} ${RunningX64}
            ReadRegStr $R1 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate" "path"
          ${Else}
            ReadRegStr $R1 HKLM "SOFTWARE\Microsoft\EdgeUpdate" "path"
          ${EndIf}
          ${If} $R1 == ""
            ReadRegStr $R1 HKCU "SOFTWARE\Microsoft\EdgeUpdate" "path"
          ${EndIf}
          ${If} $R1 != ""
            ; Chromium updater docs: https://source.chromium.org/chromium/chromium/src/+/main:docs/updater/user_manual.md
            ; Modified from "HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Microsoft EdgeWebView\ModifyPath"
            ExecWait `"$R1" /install appguid=${WEBVIEW2APPGUID}&needsadmin=true` $1
            ${If} $1 = 0
              DetailPrint "$(webview2InstallSuccess)"
            ${Else}
              MessageBox MB_ICONEXCLAMATION|MB_ABORTRETRYIGNORE "$(webview2InstallError)" IDIGNORE ignore IDRETRY update_webview
              Quit
              ignore:
            ${EndIf}
          ${EndIf}
      ${EndIf}
    !endif
  ${EndIf}
SectionEnd

Section Install
  SetOutPath $INSTDIR

  !ifmacrodef NSIS_HOOK_PREINSTALL
    !insertmacro NSIS_HOOK_PREINSTALL
  !endif

  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"

  ; Copy main executable
  File "${MAINBINARYSRCPATH}"

  ; Copy resources
  {{#each resources_dirs}}
    CreateDirectory "$INSTDIR\\{{this}}"
  {{/each}}
  {{#each resources}}
    File /a "/oname={{this.[1]}}" "{{no-escape @key}}"
  {{/each}}

  ; Neurova 首装管理员凭据：账号页通过校验后写入，后端首启消费后删除
  ${If} "$AdminWritten" == "1"
    CreateDirectory "$INSTDIR\backend\data"
    WriteINIStr "$INSTDIR\backend\data\bootstrap_admin.ini" "bootstrap" "username" "$AdminUsername"
    WriteINIStr "$INSTDIR\backend\data\bootstrap_admin.ini" "bootstrap" "password" "$AdminPassword"
    ; 口令不再留在安装器内存
    StrCpy $AdminPassword ""
    StrCpy $AdminPassword2 ""
  ${EndIf}

  ; Neurova：后端以普通用户运行时需在安装目录写 data/ logs/ agent_workspaces/
  ; （SQLite/日志/工作区），Program Files 型目录默认对 Users 只读会令后端
  ; 启动即崩 → 在 backend 根目录授予 Users 组修改权（(OI)(CI) 继承到新建
  ; 子对象即满足；**严禁 /T 递归**——数万文件逐个改 ACL 会卡死安装器）。
  ; 用 SID 避开非英文系统组名。
  DetailPrint "正在配置运行目录权限..."
  nsExec::Exec 'icacls "$INSTDIR\backend" /grant *S-1-5-32-545:(OI)(CI)M'
  Pop $0

  ; Copy external binaries
  {{#each binaries}}
    File /a "/oname={{this}}" "{{no-escape @key}}"
  {{/each}}

  ; Create file associations
  {{#each file_associations as |association| ~}}
    {{#each association.ext as |ext| ~}}
       !insertmacro APP_ASSOCIATE "{{ext}}" "{{or association.name ext}}" "{{association-description association.description ext}}" "$INSTDIR\${MAINBINARYNAME}.exe,0" "Open with ${PRODUCTNAME}" "$INSTDIR\${MAINBINARYNAME}.exe $\"%1$\""
    {{/each}}
  {{/each}}

  ; Register deep links
  {{#each deep_link_protocols as |protocol| ~}}
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}" "URL Protocol" ""
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}" "" "URL:${BUNDLEID} protocol"
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}\DefaultIcon" "" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\",0"
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}\shell\open\command" "" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\" $\"%1$\""
  {{/each}}

  ; Neurova：桌面快捷方式恒建（原完成页勾选位已让给「开机自启」）；
  ; 升级覆盖安装时幂等刷新；静默 /NS 模式尊重跳过。
  ${If} $NoShortcutMode = 0
    CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    !insertmacro SetLnkAppUserModelId "$DESKTOP\${PRODUCTNAME}.lnk"
  ${EndIf}

  ; Create uninstaller
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Save $INSTDIR in registry for future installations
  WriteRegStr SHCTX "${MANUPRODUCTKEY}" "" $INSTDIR

  !if "${INSTALLMODE}" == "both"
    ; Save install mode to be selected by default for the next installation such as updating
    ; or when uninstalling
    WriteRegStr SHCTX "${UNINSTKEY}" $MultiUser.InstallMode 1
  !endif

  ; Remove old main binary if it doesn't match new main binary name
  ReadRegStr $OldMainBinaryName SHCTX "${UNINSTKEY}" "MainBinaryName"
  ${If} $OldMainBinaryName != ""
  ${AndIf} $OldMainBinaryName != "${MAINBINARYNAME}.exe"
    Delete "$INSTDIR\$OldMainBinaryName"
  ${EndIf}

  ; Save current MAINBINARYNAME for future updates
  WriteRegStr SHCTX "${UNINSTKEY}" "MainBinaryName" "${MAINBINARYNAME}.exe"

  ; Registry information for add/remove programs
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${PRODUCTNAME}"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayIcon" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\""
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr SHCTX "${UNINSTKEY}" "Publisher" "${MANUFACTURER}"
  WriteRegStr SHCTX "${UNINSTKEY}" "InstallLocation" "$\"$INSTDIR$\""
  WriteRegStr SHCTX "${UNINSTKEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoModify" "1"
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoRepair" "1"

  ${GetSize} "$INSTDIR" "/M=uninstall.exe /S=0K /G=0" $0 $1 $2
  IntOp $0 $0 + ${ESTIMATEDSIZE}
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD SHCTX "${UNINSTKEY}" "EstimatedSize" "$0"

  !if "${HOMEPAGE}" != ""
    WriteRegStr SHCTX "${UNINSTKEY}" "URLInfoAbout" "${HOMEPAGE}"
    WriteRegStr SHCTX "${UNINSTKEY}" "URLUpdateInfo" "${HOMEPAGE}"
    WriteRegStr SHCTX "${UNINSTKEY}" "HelpLink" "${HOMEPAGE}"
  !endif

  ; Create start menu shortcut
  !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    Call CreateOrUpdateStartMenuShortcut
  !insertmacro MUI_STARTMENU_WRITE_END

  ; Create desktop shortcut for silent and passive installers
  ; because finish page will be skipped
  ${If} $PassiveMode = 1
  ${OrIf} ${Silent}
    Call CreateOrUpdateDesktopShortcut
  ${EndIf}

  !ifmacrodef NSIS_HOOK_POSTINSTALL
    !insertmacro NSIS_HOOK_POSTINSTALL
  !endif

  ; Auto close this page for passive mode
  ${If} $PassiveMode = 1
    SetAutoClose true
  ${EndIf}
SectionEnd

Function .onInstSuccess
  ; Check for `/R` flag only in silent and passive installers because
  ; GUI installer has a toggle for the user to (re)start the app
  ${If} $PassiveMode = 1
  ${OrIf} ${Silent}
    ${GetOptions} $CMDLINE "/R" $R0
    ${IfNot} ${Errors}
      ${GetOptions} $CMDLINE "/ARGS" $R0
      nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" "$R0"
    ${EndIf}
  ${EndIf}
FunctionEnd

Function un.onInit
  !insertmacro SetContext

  !if "${INSTALLMODE}" == "both"
    !insertmacro MULTIUSER_UNINIT
  !endif

  !insertmacro MUI_UNGETLANGUAGE

  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}

  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}
FunctionEnd

Section Uninstall

  !ifmacrodef NSIS_HOOK_PREUNINSTALL
    !insertmacro NSIS_HOOK_PREUNINSTALL
  !endif

  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"

  ; Delete the app directory and its content from disk
  ; Copy main executable
  Delete "$INSTDIR\${MAINBINARYNAME}.exe"

  ; Delete resources
  {{#each resources}}
    Delete "$INSTDIR\\{{this.[1]}}"
  {{/each}}

  ; Delete external binaries
  {{#each binaries}}
    Delete "$INSTDIR\\{{this}}"
  {{/each}}

  ; Delete app associations
  {{#each file_associations as |association| ~}}
    {{#each association.ext as |ext| ~}}
      !insertmacro APP_UNASSOCIATE "{{ext}}" "{{or association.name ext}}"
    {{/each}}
  {{/each}}

  ; Delete deep links
  {{#each deep_link_protocols as |protocol| ~}}
    ReadRegStr $R7 SHCTX "Software\Classes\\{{protocol}}\shell\open\command" ""
    ${If} $R7 == "$\"$INSTDIR\${MAINBINARYNAME}.exe$\" $\"%1$\""
      DeleteRegKey SHCTX "Software\Classes\\{{protocol}}"
    ${EndIf}
  {{/each}}


  ; Delete uninstaller
  Delete "$INSTDIR\uninstall.exe"

  {{#each resources_ancestors}}
  RMDir /REBOOTOK "$INSTDIR\\{{this}}"
  {{/each}}
  RMDir "$INSTDIR"

  ; Remove shortcuts if not updating
  ${If} $UpdateMode <> 1
    !insertmacro DeleteAppUserModelId

    ; Remove start menu shortcut
    !insertmacro MUI_STARTMENU_GETFOLDER Application $AppStartMenuFolder
    !insertmacro IsShortcutTarget "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      !insertmacro UnpinShortcut "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
      Delete "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
      RMDir "$SMPROGRAMS\$AppStartMenuFolder"
    ${EndIf}
    !insertmacro IsShortcutTarget "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      !insertmacro UnpinShortcut "$SMPROGRAMS\${PRODUCTNAME}.lnk"
      Delete "$SMPROGRAMS\${PRODUCTNAME}.lnk"
    ${EndIf}

    ; Remove desktop shortcuts
    !insertmacro IsShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      !insertmacro UnpinShortcut "$DESKTOP\${PRODUCTNAME}.lnk"
      Delete "$DESKTOP\${PRODUCTNAME}.lnk"
    ${EndIf}
  ${EndIf}

  ; Remove registry information for add/remove programs
  !if "${INSTALLMODE}" == "both"
    DeleteRegKey SHCTX "${UNINSTKEY}"
  !else if "${INSTALLMODE}" == "perMachine"
    DeleteRegKey HKLM "${UNINSTKEY}"
  !else
    DeleteRegKey HKCU "${UNINSTKEY}"
  !endif

  ; Removes the Autostart entry for ${PRODUCTNAME} from the HKCU Run key if it exists.
  ; This ensures the program does not launch automatically after uninstallation if it exists.
  ; If it doesn't exist, it does nothing.
  ; We do this when not updating (to preserve the registry value on updates)
  ${If} $UpdateMode <> 1
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${PRODUCTNAME}"
  ${EndIf}

  ; Delete app data if the checkbox is selected
  ; and if not updating
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    ; Clear the install location $INSTDIR from registry
    DeleteRegKey SHCTX "${MANUPRODUCTKEY}"
    DeleteRegKey /ifempty SHCTX "${MANUKEY}"

    ; Clear the install language from registry
    DeleteRegValue HKCU "${MANUPRODUCTKEY}" "Installer Language"
    DeleteRegKey /ifempty HKCU "${MANUPRODUCTKEY}"
    DeleteRegKey /ifempty HKCU "${MANUKEY}"

    SetShellVarContext current
    RmDir /r "$APPDATA\${BUNDLEID}"
    RmDir /r "$LOCALAPPDATA\${BUNDLEID}"

    ; Neurova：用户产生的全部数据（勾选"保留数据"时以下都不删）——
    ; ① 安装目录内的后端数据（用户库/记忆/聊天/工作区/日志/引导凭据）
    RmDir /r "$INSTDIR\backend\data"
    RmDir /r "$INSTDIR\agent_workspaces"
    RmDir /r "$INSTDIR\logs"
    RmDir /r "$INSTDIR\backend\logs"
    Delete "$INSTDIR\backend\backend.log"
    ; ② 后端运行期可能在用户目录生成的数据（双写兜底）
    RmDir /r "$APPDATA\${PRODUCTNAME}\agent_workspaces"
    RmDir /r "$APPDATA\${PRODUCTNAME}\data"
    RmDir /r "$APPDATA\${PRODUCTNAME}\logs"
    ; ③ 彻底清安装目录（此刻程序文件已删，仅剩运行时残留）
    RmDir /r "$INSTDIR"
  ${EndIf}

  !ifmacrodef NSIS_HOOK_POSTUNINSTALL
    !insertmacro NSIS_HOOK_POSTUNINSTALL
  !endif

  ; Auto close if passive mode or updating
  ${If} $PassiveMode = 1
  ${OrIf} $UpdateMode = 1
    SetAutoClose true
  ${EndIf}
SectionEnd

Function RestorePreviousInstallLocation
  ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
  StrCmp $4 "" +2 0
    StrCpy $INSTDIR $4
FunctionEnd

Function Skip
  Abort
FunctionEnd

Function SkipIfPassive
  ${IfThen} $PassiveMode = 1  ${|} Abort ${|}
FunctionEnd

; ==================== 单页自定义安装器 ====================
; 参考现代单页安装器（Hero 品牌图 + 协议勾选 + 一键安装）。
; 配色 = 应用品牌深靛蓝（#0A0E1F→#1A2148 渐变 + 主色 #4D6BFE 按钮位图）。
; Hero 位图内烙品牌介绍与开源地址/官网（中英双图按安装器语言挑选）。
; 彩色大按钮 = BS_BITMAP 原生位图按钮（无第三方插件）；点击即推进向导。

Function SkipDirIfFastOrPassive
  ${IfThen} $PassiveMode = 1 ${|} Abort ${|}
  ${IfThen} $FastInstall = 1 ${|} Abort ${|}
FunctionEnd

Function OnEulaLinkClick
  ; 协议链接 → 官网法律页（与前端 /terms 同源）
  ExecShell "open" "https://www.neurova.top/terms"
FunctionEnd

Function OnCustomInstallClick
  ; 自定义安装：走目录页（Driver Booster 式次级入口）
  StrCpy $FastInstall 0
  GetDlgItem $0 $HWNDPARENT 1
  SendMessage $0 ${BM_CLICK} 0 0
FunctionEnd

Function OnInstallBtnClick
  ; 一键安装：协议校验 → 推进（FastInstall=1 跳过目录页）
  ${NSD_GetState} $hEulaCheck $0
  ${If} $0 <> ${BST_CHECKED}
    MessageBox MB_ICONEXCLAMATION "$(nsEulaWarn)"
    Abort
  ${EndIf}
  GetDlgItem $0 $HWNDPARENT 1
  SendMessage $0 ${BM_CLICK} 0 0
FunctionEnd

Function PageWelcome
  StrCpy $FastInstall 1

  ; 隐藏 MUI header（单页安装器整窗展示）。MUI2 header 控件 ID：
  ; 1037=标题 1038=副标题 1039=位图 1256=branding（Interface.nsh 实证）
  GetDlgItem $R0 $HWNDPARENT 1037
  ShowWindow $R0 0
  GetDlgItem $R0 $HWNDPARENT 1038
  ShowWindow $R0 0
  GetDlgItem $R0 $HWNDPARENT 1039
  ShowWindow $R0 0
  GetDlgItem $R0 $HWNDPARENT 1256
  ShowWindow $R0 0

  ; 页面 dialog 拉到父窗口 client 全区（含 header 腾出的空间）——
  ; 否则顶部残留 header 高度的空白带
  System::Alloc 16
  Pop $R9
  System::Call "user32::GetClientRect(p $HWNDPARENT, p $R9)"
  System::Call "*$R9(i, i, i .R8, i .R7)"
  System::Free $R9

  nsDialogs::Create 1018
  Pop $hCustDlg
  SetCtlColors $hCustDlg "" 0xFFFFFF  ; 底部白条（Hero 覆盖上部）
  System::Call "user32::SetWindowPos(p $hCustDlg, p 0, i 0, i 0, i $R8, i $R7, i 0x10)"

  ; Hero 位图 1:1 贴（496x150，占页面上部；中英按安装器语言挑选）。
  ; 编译期路径：bundler 的 makensis cwd = target/release/nsis/x64，
  ; 相对上行四级即 src-tauri/nsis/assets；独立验证时 expand 脚本注入绝对路径。
  File /oname=$PLUGINSDIR\hero.bmp "..\..\..\..\nsis\assets\hero_zh.bmp"
  File /oname=$PLUGINSDIR\hero_en.bmp "..\..\..\..\nsis\assets\hero_en.bmp"
  ${NSD_CreateBitmap} 0 0 1u 1u ""
  Pop $hHeroBitmap
  ${NSD_SetImage} $hHeroBitmap "$PLUGINSDIR\hero.bmp" "$PLUGINSDIR\hero.bmp"
  ${If} $LANGUAGE <> ${LANG_SIMPCHINESE}
    ${NSD_SetImage} $hHeroBitmap "$PLUGINSDIR\hero_en.bmp" "$PLUGINSDIR\hero_en.bmp"
  ${EndIf}

  ; 像素布局（页面 client 尺寸运行时获取，DPI 安全）
  System::Alloc 16
  Pop $R1
  System::Call "user32::GetClientRect(p $hCustDlg, p $R1)"
  System::Call "*$R1(i, i, i .R2, i .R3)"   ; R2=页宽 R3=页高
  System::Free $R1
  ; Hero 贴满页宽、按位图纵横比定高（496:150）
  IntOp $R4 $R2 * 150
  IntOp $R4 $R4 / 496
  System::Call "user32::SetWindowPos(p $hHeroBitmap, p 0, i 0, i 0, i $R2, i $R4, i 0x10)"

  ; 下部控件区基线 = Hero 底 + 10px
  IntOp $R5 $R4 + 10

  ${NSD_CreateCheckBox} 1u 1u 1u 1u "$(nsEulaPre)"
  Pop $hEulaCheck
  System::Call "user32::SetWindowPos(p $hEulaCheck, p 0, i 14, i $R5, i 250, i 22, i 0x10)"
  ${NSD_CreateLink} 1u 1u 1u 1u "$(nsEulaLink)"
  Pop $hEulaLink
  ${NSD_OnClick} $hEulaLink OnEulaLinkClick
  SetCtlColors $hEulaLink 0x4D6BFE transparent
  IntOp $1 $R2 - 210
  System::Call "user32::SetWindowPos(p $hEulaLink, p 0, i $1, i $R5, i 196, i 22, i 0x10)"

  ; 安装位置行（只读展示；修改走「自定义安装」）
  IntOp $R5 $R5 + 32
  ${NSD_CreateLabel} 1u 1u 1u 1u "$(nsPathLabel)"
  Pop $0
  SetCtlColors $0 0x1A2148 transparent
  System::Call "user32::SetWindowPos(p $0, p 0, i 14, i $R5, i 66, i 22, i 0x10)"
  ${NSD_CreateText} 1u 1u 1u 1u "$INSTDIR"
  Pop $hPathText
  SendMessage $hPathText ${EM_SETREADONLY} 1 0
  IntOp $1 $R2 - 24
  IntOp $2 $R5 - 2
  System::Call "user32::SetWindowPos(p $hPathText, p 0, i 84, i $2, i $1, i 24, i 0x10)"

  ; 一键安装大按钮（原生位图按钮 240x58 品牌主色胶囊，1:1 不裁切；
  ; 位图归控件所有，不 DeleteObject——删了即空白）
  File /oname=$PLUGINSDIR\btn_install.bmp "..\..\..\..\nsis\assets\btn_install.bmp"
  ${NSD_CreateButton} 1u 1u 1u 1u "$(nsInstallBtn)"
  Pop $hBtnInstall
  ${NSD_OnClick} $hBtnInstall OnInstallBtnClick
  System::Call "user32::GetWindowLong(p $hBtnInstall, i -16) p .r0"
  IntOp $0 $0 | 0x80            ; BS_BITMAP
  System::Call "user32::SetWindowLong(p $hBtnInstall, i -16, p r0)"
  System::Call 'user32::LoadImage(p 0, t "$PLUGINSDIR\btn_install.bmp", i 0, i 0, i 0, i 0x10) p .s' ; LR_LOADFROMFILE
  Pop $1
  SendMessage $hBtnInstall ${BM_SETIMAGE} ${IMAGE_BITMAP} $1
  IntOp $R5 $R5 + 34
  IntOp $0 $R2 - 200
  IntOp $0 $0 / 2
  System::Call "user32::SetWindowPos(p $hBtnInstall, p 0, i $0, i $R5, i 200, i 48, i 0x10)"

  ; 自定义安装小链接（按钮正下方居中，Driver Booster 式次级入口）
  ${NSD_CreateLink} 1u 1u 1u 1u "$(nsCustomInstall)"
  Pop $0
  ${NSD_OnClick} $0 OnCustomInstallClick
  SetCtlColors $0 0x8A93A8 transparent
  IntOp $R5 $R5 + 52
  IntOp $2 $R2 - 160
  IntOp $2 $2 / 2
  System::Call "user32::SetWindowPos(p $0, p 0, i $2, i $R5, i 160, i 20, i 0x10)"

  ${NSD_SetFocus} $hBtnInstall
  nsDialogs::Show
FunctionEnd

Function PageLeaveWelcome
  ${NSD_GetState} $hEulaCheck $0
  ${If} $0 <> ${BST_CHECKED}
    MessageBox MB_ICONEXCLAMATION "$(nsEulaWarn)"
    Abort
  ${EndIf}
  ${NSD_GetText} $hPathText $0
  ${If} $0 == ""
    StrCpy $INSTDIR "$INSTDIR"
  ${Else}
    StrCpy $INSTDIR $0
  ${EndIf}
FunctionEnd
Function un.SkipIfPassive
  ${IfThen} $PassiveMode = 1  ${|} Abort ${|}
FunctionEnd

Function CreateOrUpdateStartMenuShortcut
  ; We used to use product name as MAINBINARYNAME
  ; migrate old shortcuts to target the new MAINBINARYNAME
  StrCpy $R0 0

  !insertmacro IsShortcutTarget "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\$OldMainBinaryName"
  Pop $0
  ${If} $0 = 1
    !insertmacro SetShortcutTarget "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    StrCpy $R0 1
  ${EndIf}

  !insertmacro IsShortcutTarget "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\$OldMainBinaryName"
  Pop $0
  ${If} $0 = 1
    !insertmacro SetShortcutTarget "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    StrCpy $R0 1
  ${EndIf}

  ${If} $R0 = 1
    Return
  ${EndIf}

  ; Skip creating shortcut if in update mode or no shortcut mode
  ; but always create if migrating from wix
  ${If} $WixMode = 0
    ${If} $UpdateMode = 1
    ${OrIf} $NoShortcutMode = 1
      Return
    ${EndIf}
  ${EndIf}

  !if "${STARTMENUFOLDER}" != ""
    CreateDirectory "$SMPROGRAMS\$AppStartMenuFolder"
    CreateShortcut "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    !insertmacro SetLnkAppUserModelId "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
  !else
    CreateShortcut "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    !insertmacro SetLnkAppUserModelId "$SMPROGRAMS\${PRODUCTNAME}.lnk"
  !endif
FunctionEnd

Function CreateOrUpdateDesktopShortcut
  ; We used to use product name as MAINBINARYNAME
  ; migrate old shortcuts to target the new MAINBINARYNAME
  !insertmacro IsShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\$OldMainBinaryName"
  Pop $0
  ${If} $0 = 1
    !insertmacro SetShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Return
  ${EndIf}

  ; Skip creating shortcut if in update mode or no shortcut mode
  ; but always create if migrating from wix
  ${If} $WixMode = 0
    ${If} $UpdateMode = 1
    ${OrIf} $NoShortcutMode = 1
      Return
    ${EndIf}
  ${EndIf}

  CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  !insertmacro SetLnkAppUserModelId "$DESKTOP\${PRODUCTNAME}.lnk"
FunctionEnd
