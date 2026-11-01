; Inno Setup script for Zapret Strategy Tuner
; Установка в LocalAppData текущего пользователя, без Program Files.
; Ярлык запускает exe с манифестом requireAdministrator (UAC).

#define MyAppName "Zapret Strategy Tuner"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.2"
#endif
#define MyAppPublisher "FT-123"
#define MyAppURL "https://github.com/FT-123/fuzze-winws"
#define MyAppExeName "fuzzer.exe"

[Setup]
AppId={{8F3B2C1D-7A4E-4F6B-9C21-5D8E7A6B4C10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Zapret Strategy Tuner
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=ZapretStrategyTuner-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
SetupLogging=yes
LicenseFile=..\LICENSE.txt
InfoBeforeFile=..\THIRD_PARTY.md

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\build\stage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Автонастройка обхода DPI"
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Автонастройка обхода DPI"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /F /IM winws.exe /IM winws2.exe >nul 2>&1"; Flags: runhidden; RunOnceId: "stop-winws"

[UninstallDelete]
; Личные списки, settings.json, history.json и auto-config.bat не удаляем:
; они созданы пользователем и не входят в установщик.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\logs"
