; Мастер установки «Таймера вебинара» (Inno Setup 6). Собирается из tools/build_webinar_dist.py:
;   ISCC /DAppVersion=1.2.0 /DSourceDir=<папка с exe> /DOutDir=INSTALL /DIcon=<значок> webinar_setup.iss
; Ставится для текущего пользователя, без прав администратора (%LOCALAPPDATA%\Programs\Таймер вебинара).
; Обновление поверх меняет только файлы программы: папка data (шаблоны, настройки, журнал) не трогается,
; при удалении программы она тоже остаётся.

#define AppName "Таймер вебинара"
#define AppExe "Таймер вебинара.exe"
; /DUpdate=1 — лёгкий установщик для обновлений: без media (видео, фон, шрифт уже стоят у пользователя)
#ifdef Update
  #define OutName "webinar-timer-update-" + AppVersion
  #define Skip "data\*,media\*"
#else
  #define OutName "Установка — " + AppName + " " + AppVersion
  #define Skip "data\*"
#endif

[Setup]
AppId={{E4F5E0C0-61A9-4003-8571-50BDDAAC123E}
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
; видео уже сжато — сильное сжатие только замедлит сборку и установку
Compression=lzma2/fast
SolidCompression=no
; таймер обычно в трее — перед обновлением закрыть его (и запустить снова в конце)
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; при обновлении — убрать библиотеки и шаблоны прошлой версии (имена могли поменяться); data не трогаем
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\templates\*.json"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "{#Skip}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
#ifdef Update
; обновление из таймера ставится тихо — после него таймер запускается снова сам
; (полный установщик при тихом развёртывании таймер не запускает)
Filename: "{app}\{#AppExe}"; Flags: nowait skipifnotsilent
#endif
