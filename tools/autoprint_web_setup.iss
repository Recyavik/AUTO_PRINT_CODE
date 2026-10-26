; Мастер установки AutoPrintCode Веб (Inno Setup 6). Собирается из tools/build_autoprint_web_dist.py:
;   ISCC /DAppVersion=0.6.7 /DSourceDir=<папка приложения> /DOutDir=INSTALL /DIcon=<значок> autoprint_web_setup.iss
; Внутри — своя копия Node.js (node\node.exe): ставить Node пользователю не нужно. Ярлык запускает помощника печати
; без окна (conhost --headless), он открывает страницу в браузере. Ставится для текущего пользователя, без прав
; администратора. Обновление поверх меняет только файлы программы: папка data (образцы, настройки) не трогается.
; /DUpdate=1 — установщик обновления для GitHub (autoprintcode-web-update-<версия>.exe): помощник запускает его
; тихо; после установки он сам запускает помощника снова.

#define AppName "AutoPrintCode Веб"
#ifdef Update
  #define OutName "autoprintcode-web-update-" + AppVersion
#else
  #define OutName "Установка — AutoPrintCode Веб " + AppVersion
#endif

[Setup]
AppId={{5397B91A-35B8-4F46-B8FA-18168E601001}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=1Т
DefaultDirName={autopf}\AutoPrintCode Web
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename={#OutName}
SetupIconFile={#Icon}
UninstallDisplayIcon={app}\autoprintcode-web.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
; помощник печати (node.exe из папки программы) — закрыть перед обновлением
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; при обновлении — убрать файлы прошлой версии (страница, библиотеки, Node); data не трогаем
Type: filesandordirs; Name: "{app}\dist"
Type: filesandordirs; Name: "{app}\node_modules"
Type: filesandordirs; Name: "{app}\server"
Type: filesandordirs; Name: "{app}\shared"
Type: filesandordirs; Name: "{app}\node"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "data\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{sys}\conhost.exe"; Parameters: "--headless ""{app}\node\node.exe"" ""{app}\server\main.ts"""; WorkingDir: "{app}"; IconFilename: "{app}\autoprintcode-web.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{sys}\conhost.exe"; Parameters: "--headless ""{app}\node\node.exe"" ""{app}\server\main.ts"""; WorkingDir: "{app}"; IconFilename: "{app}\autoprintcode-web.ico"; Tasks: desktopicon

[Run]
Filename: "{sys}\conhost.exe"; Parameters: "--headless ""{app}\node\node.exe"" ""{app}\server\main.ts"""; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
#ifdef Update
Filename: "{sys}\conhost.exe"; Parameters: "--headless ""{app}\node\node.exe"" ""{app}\server\main.ts"""; WorkingDir: "{app}"; Flags: nowait skipifnotsilent
#endif

[UninstallRun]
; автозапуск помощника вместе с Windows (если включали в настройках) — убрать
Filename: "{sys}\reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v AutoPrintCode /f"; Flags: runhidden; RunOnceId: "AutostartOff"
