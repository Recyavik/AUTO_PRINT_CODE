; Установщик AutoPrintCode (Inno Setup 6.3+). Обычно собирается из tools\build_exe.py:
;   ISCC /DAppVersion=0.5.0 /DAppNumVersion=0.5.0.0 /DSourceDir=..\dist\AutoPrintCode /DOutputDir=..\dist installer\AutoPrintCode.iss
;
; Сначала Windows спрашивает, для кого ставить (стандартное окно Inno Setup):
; - для всех пользователей (по умолчанию, нужны права администратора) — в Program Files. Данные каждого
;   пользователя — в %APPDATA%\AutoPrintCode; обновляется программа установщиком из релиза (с запросом прав);
; - только для меня — без прав администратора, в %LOCALAPPDATA%\Programs\AutoPrintCode, данные — в data\
;   рядом с программой, обновляется сама.
; Затем страница «Как установить»:
; - Установить. Ярлык в «Пуске», удаление через «Параметры → Приложения». Прежняя копия «только для меня»
;   при установке для всех удаляется, а её занятия и настройки программа перенесёт при первом запуске.
; - Если программа уже установлена — «Обновить установленную версию»: та же папка, без лишних вопросов.
; - Портативная версия: просто папка с программой (например, на флешке). Ничего не прописывается в Windows —
;   ни ярлыков, ни записи в «Приложениях»; образцы и настройки — в папке data рядом с программой.
; Данные (образцы, настройки, журнал) не трогают ни обновление, ни удаление программы.
;
; Тихая установка (и обновление поверх): AutoPrintCode-X.Y.Z-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
;   (+ /CURRENTUSER — только для текущего пользователя; + /RELAUNCH=1 — запустить программу после установки)
; Тихо и портативно: ... /VERYSILENT /CURRENTUSER /PORTABLE=1 /DIR="E:\AutoPrintCode"

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppNumVersion
  #define AppNumVersion "0.0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\AutoPrintCode"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef IconFile
  #define IconFile "..\build\icon.ico"
#endif

#define AppName "AutoPrintCode"
#define AppExe "AutoPrintCode.exe"
#define AppUrl "https://github.com/DanT2000/AUTO_PRINT_CODE"
; AppId не менять: по нему установщик находит прежнюю версию и обновляет её
#define AppGuid "{BC0222C7-A45D-4D77-A7C6-1EB7F2C4FB28}"

[Setup]
AppId={#StringChange(AppGuid, "{", "{{")}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppNumVersion}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; папку спрашиваем сами: при обновлении страница пропускается (ShouldSkipPage)
DisableDirPage=no
UsePreviousAppDir=yes
DirExistsWarning=no
; по умолчанию — для всех пользователей (Program Files); «только для меня» — без прав администратора
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
UsePreviousPrivileges=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExe}
; без номера: после автообновления программа сама поправит DisplayVersion в «Приложениях»
UninstallDisplayName={#AppName}
; портативная версия — без деинсталлятора и без записи в «Приложениях»
Uninstallable=not IsPortable
CreateUninstallRegKey=not IsPortable
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; перед заменой файлов закрыть запущенную программу (в тихом режиме — без вопросов)
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ru.LaunchApp=Запустить AutoPrintCode
en.LaunchApp=Launch AutoPrintCode
ru.ModeCaption=Как установить
en.ModeCaption=How to install
ru.ModeDescription=Обычная установка или портативная версия
en.ModeDescription=Regular installation or portable copy
ru.ModeText=Установка: AutoPrintCode появится в меню «Пуск», будет обновляться сам, удаляется через «Параметры → Приложения».%n%nПортативная версия: просто папка с программой — например, на флешке. В Windows ничего не прописывается; образцы и настройки хранятся в папке data рядом с программой.
en.ModeText=Install: AutoPrintCode appears in the Start menu, keeps itself up to date and is removed via Settings → Apps.%n%nPortable: just a folder with the program, e.g. on a USB stick. Nothing is registered in Windows; samples and settings live in the data folder next to the program.
ru.ModeOldCopy=%n%nУ вас стоит копия «только для меня» (%1). Она будет удалена, а занятия и настройки программа перенесёт сама при первом запуске.
en.ModeOldCopy=%n%nA per-user copy is installed (%1). It will be removed; lessons and settings are moved over on first launch.
ru.ModeInstall=Установить (рекомендуется)
en.ModeInstall=Install (recommended)
ru.ModeInstallAll=Установить для всех пользователей — в Program Files (рекомендуется)
en.ModeInstallAll=Install for all users — to Program Files (recommended)
ru.ModeUpdate=Обновить установленную версию %1 → {#AppVersion}
en.ModeUpdate=Update the installed version %1 → {#AppVersion}
ru.ModePortable=Портативная версия — распаковать в папку
en.ModePortable=Portable — unpack to a folder
ru.OldPrograms=Старые программы:
en.OldPrograms=Old programs:
ru.RemoveTimer=Удалить «Таймер вебинара» — он теперь внутри AutoPrintCode (раздел «Эфир»); шаблоны, видео зарядки и фон перенесутся
en.RemoveTimer=Remove «Webinar timer» — it is now part of AutoPrintCode («Efir»); templates, video and background are moved over
ru.NotWritable=В папку%n%n%1%n%nнет права записи (нужны права администратора).%n%nВыберите другую папку, например:%n%2
en.NotWritable=No write access to%n%n%1%n%n(administrator rights required).%n%nPlease choose another folder, for example:%n%2

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Check: not IsPortable
; «Таймер вебинара» (отдельная программа Виктора) теперь — раздел «Эфир»: шаблоны, видео и фон переносятся
Name: "removetimer"; Description: "{cm:RemoveTimer}"; GroupDescription: "{cm:OldPrograms}"; Check: TimerInstalled and not IsPortable

[InstallDelete]
; библиотеки прежней версии убираются целиком, чтобы не смешались с новыми; data\ не трогается
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\_internal.old*"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "\data"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Check: not IsPortable
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; программа — от имени пользователя, даже если установщик работал с правами администратора
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent runasoriginaluser
; обновление из программы (тихо, /RELAUNCH=1): после установки запустить её снова
Filename: "{app}\{#AppExe}"; Parameters: "--updated"; WorkingDir: "{app}"; Flags: nowait runasoriginaluser; Check: WantRelaunch

[UninstallDelete]
; файлы, которые программа поставила сама при автообновлении (их нет в журнале установщика);
; data\ с образцами и настройками остаётся
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\_internal.old*"

[Code]
var
  ModePage: TInputOptionWizardPage;
  Installed: Boolean;
  InstalledDir, InstalledVersion: String;
  AutoDir: String;   // папка, которую подставили сами (если человек её не менял — меняем при смене режима)
  OldUserCopy: Boolean;   // установка для всех, а у пользователя стоит копия «только для меня» — удалить её
  OldUserDir, OldUninstaller: String;

const
  // старый AutoPrintCode Виктора (другой AppId, ставился в ту же папку) и его «Таймер вебинара»
  VictorAppKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{EEEA90BF-80BD-47E9-BC98-2C3C3F21B616}_is1';
  TimerAppKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{E4F5E0C0-61A9-4003-8571-50BDDAAC123E}_is1';

function FindUninstaller(Key: String; var Uninst, Dir: String): Boolean;
begin
  Result := (RegQueryStringValue(HKCU, Key, 'UninstallString', Uninst) and RegQueryStringValue(HKCU, Key, 'InstallLocation', Dir))
    or (RegQueryStringValue(HKLM, Key, 'UninstallString', Uninst) and RegQueryStringValue(HKLM, Key, 'InstallLocation', Dir));
  if Result then
    Dir := RemoveBackslashUnlessRoot(Dir);
end;

function TimerInstalled: Boolean;
var
  U, D: String;
begin
  Result := FindUninstaller(TimerAppKey, U, D);
end;

procedure RunUninstaller(Uninst: String; WaitFor: String);
var
  Code, N: Integer;
begin
  if not Exec(RemoveQuotes(Uninst), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Log('Uninstaller failed: ' + Uninst + ' ' + SysErrorMessage(Code))
  else begin
    // деинсталлятор Inno копирует себя во временную папку и сразу возвращается — ждём, пока он уберёт себя
    N := 0;
    while (WaitFor <> '') and FileExists(WaitFor) and (N < 120) do begin
      Sleep(500);
      N := N + 1;
    end;
  end;
end;

procedure CopyTree(Src, Dst: String);
var
  F: TFindRec;
begin
  if not DirExists(Src) then
    exit;
  ForceDirectories(Dst);
  if FindFirst(AddBackslash(Src) + '*', F) then
  try
    repeat
      if (F.Name <> '.') and (F.Name <> '..') then begin
        if F.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          CopyTree(AddBackslash(Src) + F.Name, AddBackslash(Dst) + F.Name)
        else if not FileCopy(AddBackslash(Src) + F.Name, AddBackslash(Dst) + F.Name, False) then
          Log('Not copied: ' + AddBackslash(Src) + F.Name);
      end;
    until not FindNext(F);
  finally
    FindClose(F);
  end;
end;

function DataDir: String;
begin
  // где программа держит данные: установка для всех — %APPDATA%, иначе data рядом с программой
  if IsAdminInstallMode then
    Result := ExpandConstant('{userappdata}\{#AppName}')
  else
    Result := ExpandConstant('{app}\data');
end;

procedure RemoveOldPrograms;
var
  U, D, Keep: String;
begin
  // старый AutoPrintCode Виктора: запись в «Приложениях» и его файлы убираем ДО установки (папка data остаётся)
  if FindUninstaller(VictorAppKey, U, D) then begin
    Log('Removing old AutoPrintCode (Victor): ' + D);
    RunUninstaller(U, RemoveQuotes(U));
  end;
  if WizardIsTaskSelected('removetimer') and FindUninstaller(TimerAppKey, U, D) then begin
    // сначала — копия шаблонов, настроек и файлов таймера: AutoPrintCode перенесёт их в «Эфир» при первом открытии
    Keep := AddBackslash(DataDir) + 'efir\webinar-timer';
    Log('Saving webinar timer data to ' + Keep);
    CopyTree(AddBackslash(D) + 'data', AddBackslash(Keep) + 'data');
    CopyTree(AddBackslash(D) + 'media', AddBackslash(Keep) + 'media');
    CopyTree(AddBackslash(D) + 'templates', AddBackslash(Keep) + 'templates');
    Log('Removing webinar timer: ' + D);
    RunUninstaller(U, RemoveQuotes(U));
  end;
end;

function UninstallKey: String;
begin
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppGuid}_is1';
end;

function IsPortable: Boolean;
begin
  if (ModePage = nil) or WizardSilent then
    Result := ExpandConstant('{param:portable|0}') = '1'
  else
    Result := ModePage.SelectedValueIndex = 1;
end;

function DefaultInstallDir: String;
begin
  if Installed then
    Result := InstalledDir
  else
    Result := ExpandConstant('{autopf}\{#AppName}');
end;

function WantRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;

// установка (запись в «Приложениях») в ветке реестра Root: есть и программа на месте → папка
function FindInstall(Root: Integer; var Dir: String): Boolean;
begin
  Result := RegQueryStringValue(Root, UninstallKey, 'InstallLocation', Dir);
  if Result then begin
    Dir := RemoveBackslashUnlessRoot(Dir);
    Result := FileExists(AddBackslash(Dir) + '{#AppExe}');   // запись осталась, а программы нет
  end;
end;

function DefaultPortableDir: String;
begin
  Result := ExpandConstant('{userdesktop}\{#AppName}');
end;

procedure InitializeWizard;
var
  Line, Text: String;
  Root: Integer;
begin
  // своя установка — в той ветке реестра, куда ставим сейчас: для всех — HKLM, для себя — HKCU
  if IsAdminInstallMode then Root := HKLM else Root := HKCU;
  Installed := FindInstall(Root, InstalledDir);
  if Installed then begin
    if not RegQueryStringValue(Root, UninstallKey, 'DisplayVersion', InstalledVersion) then
      InstalledVersion := '';
    Line := FmtMessage(CustomMessage('ModeUpdate'), [InstalledVersion]);
  end else if IsAdminInstallMode then
    Line := CustomMessage('ModeInstallAll')
  else
    Line := CustomMessage('ModeInstall');
  Text := CustomMessage('ModeText');
  // ставим для всех, а у пользователя есть копия «только для меня» — после установки она удаляется
  OldUserCopy := IsAdminInstallMode and FindInstall(HKCU, OldUserDir)
    and RegQueryStringValue(HKCU, UninstallKey, 'UninstallString', OldUninstaller);
  if OldUserCopy then
    Text := Text + FmtMessage(CustomMessage('ModeOldCopy'), [OldUserDir]);
  ModePage := CreateInputOptionPage(wpWelcome, CustomMessage('ModeCaption'), CustomMessage('ModeDescription'),
    Text, True, False);
  ModePage.Add(Line);
  ModePage.Add(CustomMessage('ModePortable'));
  if ExpandConstant('{param:portable|0}') = '1' then
    ModePage.SelectedValueIndex := 1
  else
    ModePage.SelectedValueIndex := 0;
  AutoDir := WizardForm.DirEdit.Text;
end;

function DirWritable(Dir: String): Boolean;
var
  Probe: String;
  Created: Boolean;
begin
  Created := not DirExists(Dir);
  if Created and not ForceDirectories(Dir) then begin
    Result := False;
    exit;
  end;
  Probe := AddBackslash(Dir) + '.autoprintcode-write-test';
  Result := SaveStringToFile(Probe, 'test', False);
  if Result then
    DeleteFile(Probe);
  if Created then
    RemoveDir(Dir);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Want: String;
begin
  Result := True;
  if CurPageID = ModePage.ID then begin
    // папку по режиму подставляем, только если человек не вписал свою — ни в мастере, ни в /DIR=
    // (NextButtonClick вызывается и при тихой установке: там папку не трогаем вовсе)
    if IsPortable then Want := DefaultPortableDir else Want := DefaultInstallDir;
    if not WizardSilent and (ExpandConstant('{param:dir|}') = '')
        and ((WizardForm.DirEdit.Text = AutoDir) or (WizardForm.DirEdit.Text = '')) then begin
      WizardForm.DirEdit.Text := Want;
      AutoDir := Want;
    end;
  end else if CurPageID = wpSelectDir then begin
    if not DirWritable(WizardDirValue) then begin
      if IsPortable then Want := DefaultPortableDir else Want := ExpandConstant('{autopf}\{#AppName}');
      MsgBox(FmtMessage(CustomMessage('NotWritable'), [WizardDirValue, Want]), mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code, N: Integer;
begin
  if (CurStep = ssInstall) and not IsPortable then
    RemoveOldPrograms;
  // новая копия для всех поставлена — прежнюю «только для меня» убрать (её data\ остаётся: программа
  // перенесёт занятия и настройки при первом запуске). Портативную установку это не касается
  if (CurStep = ssPostInstall) and OldUserCopy and not IsPortable
      and (CompareText(OldUserDir, RemoveBackslashUnlessRoot(ExpandConstant('{app}'))) <> 0) then begin
    if not Exec(RemoveQuotes(OldUninstaller), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE,
        ewWaitUntilTerminated, Code) then
      Log('Prior per-user copy was not removed: ' + SysErrorMessage(Code))
    else begin
      // программа перенесёт данные, только когда прежней копии уже нет — дождаться её удаления
      N := 0;
      while FileExists(AddBackslash(OldUserDir) + '{#AppExe}') and (N < 60) do begin
        Sleep(500);
        N := N + 1;
      end;
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // обновление установленной версии — в ту же папку, страницу выбора не показываем
  Result := (PageID = wpSelectDir) and Installed and not IsPortable;
end;
