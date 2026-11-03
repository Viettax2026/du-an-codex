#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{4E0BBD1F-7439-483F-905E-9C7F870B509A}
AppName=ZaloFlow Local
AppVersion={#AppVersion}
AppPublisher=ZaloFlow
DefaultDirName={localappdata}\Programs\ZaloFlowLocal
DefaultGroupName=ZaloFlow Local
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=dist\local-installer
OutputBaseFilename=ZaloFlow-Local-Setup-x64
SetupIconFile=assets\zaloflow.ico
UninstallDisplayIcon={app}\ZaloFlow.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=ZaloFlow.exe
RestartApplications=no
SetupLogging=yes
InfoBeforeFile=HUONG-DAN-LOCAL.txt

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Dirs]
Name: "{app}\_internal"; Attribs: hidden

[Files]
Source: "dist\ZaloFlowLocal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\ZaloFlow Local"; Filename: "{app}\ZaloFlow.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ZaloFlow.exe"; Tasks: desktopicon
Name: "{userprograms}\ZaloFlow Local"; Filename: "{app}\ZaloFlow.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ZaloFlow.exe"
Name: "{userprograms}\ZaloFlow Local - Help"; Filename: "{app}\HUONG-DAN.txt"

[Run]
Filename: "{app}\ZaloFlow.exe"; Description: "Open ZaloFlow Local"; Flags: nowait postinstall skipifsilent
