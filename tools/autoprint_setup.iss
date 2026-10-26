; Мастер установки AutoPrintCode (настольная версия, Inno Setup 6). Собирается из tools/build_autoprint_dist.py:
;   ISCC /DAppVersion=0.6.7 /DSourceDir=<папка с exe> /DOutDir=INSTALL /DIcon=<значок> autoprint_setup.iss
; Ставится для текущего пользователя, без прав администратора (%LOCALAPPDATA%\Programs\AutoPrintCode).
; Обновление поверх меняет только файлы программы: папка data (образцы, настройки, журнал) не трогается,
; при удалении программы она тоже остаётся.
; /DUpdate=1 — установщик обновления для GitHub (autoprintcode-update-<версия>.exe): программа запускает его
; тихо; после установки он сам запускает программу снова, если не передан /NORELAUNCH («установить при выходе»).

#define AppName "AutoPrintCode"
#define AppExe "AutoPrintCode.exe"
#ifdef Update
  #define OutName "autoprintcode-update-" + AppVersion
#else
  #define OutName "Установка — " + AppName + " " + AppVersion
#endif

[Setup]
AppId={{EEEA90BF-80BD-47E9-BC98-2C3C3F21B616}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=1Т
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename={#OutName}
SetupIconFile={#Icon}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
; программа обычно в трее — перед обновлением закрыть её
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; при обновлении — убрать библиотеки прошлой версии; data не трогаем
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "data\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
#ifdef Update
Filename: "{app}\{#AppExe}"; Parameters: "--updated"; Flags: nowait skipifnotsilent; Check: ShouldRelaunch
#endif

#ifdef Update
[Code]
function ShouldRelaunch: Boolean;
begin
  Result := Pos('/NORELAUNCH', UpperCase(GetCmdTail)) = 0;
end;
#endif
