; One downloadable installer. User data and activation live outside {app}.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{C38DF867-D7E9-47C2-8353-C4FA3851D152}
AppName=ZaloFlow
AppVersion={#AppVersion}
AppPublisher=Viettax
DefaultDirName={localappdata}\Programs\ZaloFlow
DefaultGroupName=ZaloFlow
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=dist\installer
OutputBaseFilename=ZaloFlow-Setup-x64
SetupIconFile=assets\zaloflow.ico
UninstallDisplayIcon={app}\ZaloFlow.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=ZaloFlow.exe
RestartApplications=no
SetupLogging=yes
InfoBeforeFile=HUONG-DAN.txt

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Dirs]
Name: "{app}\_internal"; Attribs: hidden

[Files]
Source: "dist\ZaloFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\ZaloFlow"; Filename: "{app}\ZaloFlow.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ZaloFlow.exe"; Tasks: desktopicon
Name: "{userprograms}\ZaloFlow"; Filename: "{app}\ZaloFlow.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ZaloFlow.exe"
Name: "{userprograms}\ZaloFlow - Help"; Filename: "{app}\HUONG-DAN.txt"

[Run]
Filename: "{app}\ZaloFlow.exe"; Description: "Open ZaloFlow"; Flags: nowait postinstall skipifsilent

; No UninstallDelete: database, QR sessions and activation are retained in
; %LOCALAPPDATA%\ZaloFlow. Uninstalling is not deactivation of a license seat.
