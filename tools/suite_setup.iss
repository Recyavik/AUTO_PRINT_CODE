; Общий мастер «1Т — установка инструментов» (Inno Setup 6). Собирается из tools/build_suite.py:
;   ISCC /DSuiteVersion=2026.10.26 /DTimerSetup=… /DAutoprintSetup=… /DWebSetup=… /DOutDir=INSTALL /DIcon=… suite_setup.iss
; Внутри — готовые установщики приложений; мастер ставит отмеченные галочками тихо, по очереди. У каждого
; приложения — своя папка, своя запись в «Приложениях», свои обновления и удаление; сам мастер не регистрируется.

#define SuiteName "Инструменты 1Т"

[Setup]
AppId={{18A8E2F9-18B4-47EF-912E-7BC19139284A}
AppName={#SuiteName}
AppVersion={#SuiteVersion}
AppPublisher=1Т
DefaultDirName={autopf}\1T Tools
DisableDirPage=yes
; мастер сам ничего не ставит — свою папку не создаёт
CreateAppDir=no
DisableProgramGroupPage=yes
Uninstallable=no
CreateUninstallRegKey=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=Установка — инструменты 1Т {#SuiteVersion}
SetupIconFile={#Icon}
WizardStyle=modern
Compression=none
; внутри — уже сжатые установщики
CloseApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
ru.WelcomeLabel2=Мастер установит выбранные программы 1Т: «Таймер вебинара», AutoPrintCode и AutoPrintCode Веб.%n%nКаждая программа ставится в свою папку, обновляется и удаляется отдельно. Python и Node.js не нужны. Права администратора не нужны.
ru.SelectComponentsLabel2=Отметьте программы, которые нужно установить или обновить. Уже установленные обновятся, ваши данные (шаблоны, образцы, настройки) сохранятся.

[Types]
Name: "all"; Description: "Все программы"
Name: "custom"; Description: "Выбрать"; Flags: iscustom

[Components]
Name: "timer"; Description: "Таймер вебинара — повестка, напоминания, перерыв и зарядка на экране демонстрации"; Types: all
Name: "autoprint"; Description: "AutoPrintCode — печать кода «как человек» (программа для Windows)"; Types: all
Name: "web"; Description: "AutoPrintCode Веб — то же в браузере (помощник печати + страница)"; Types: all

[Tasks]
Name: "desktopicon"; Description: "Ярлыки на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
Source: "{#TimerSetup}"; DestDir: "{tmp}"; DestName: "timer-setup.exe"; Components: timer; Flags: deleteafterinstall
Source: "{#AutoprintSetup}"; DestDir: "{tmp}"; DestName: "autoprint-setup.exe"; Components: autoprint; Flags: deleteafterinstall
Source: "{#WebSetup}"; DestDir: "{tmp}"; DestName: "web-setup.exe"; Components: web; Flags: deleteafterinstall

[Run]
Filename: "{tmp}\timer-setup.exe"; Parameters: "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS {code:Tasks}"; StatusMsg: "Устанавливается «Таймер вебинара»…"; Components: timer; Flags: waituntilterminated
Filename: "{tmp}\autoprint-setup.exe"; Parameters: "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS {code:Tasks}"; StatusMsg: "Устанавливается AutoPrintCode…"; Components: autoprint; Flags: waituntilterminated
Filename: "{tmp}\web-setup.exe"; Parameters: "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS {code:Tasks}"; StatusMsg: "Устанавливается AutoPrintCode Веб…"; Components: web; Flags: waituntilterminated

[Code]
{ ярлык на рабочем столе — как выбрано в общем мастере }
function Tasks(Param: String): String;
begin
  if WizardIsTaskSelected('desktopicon') then
    Result := '/TASKS="desktopicon"'
  else
    Result := '/TASKS=""';
end;
