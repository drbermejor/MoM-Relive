#define MyAppName "Memories of Mars Revival"
#ifndef MyAppVersion
  #define MyAppVersion "0.5.0"
#endif
#define MyAppExeName "MoMRevival.exe"

[Setup]
AppId={{D976685B-497C-4437-A511-E2C7A38F8C36}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Memories of Mars Revival Community
DefaultDirName={localappdata}\Programs\MoMRevival
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=MoMRevivalSetup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: client
Source: "..\dist\MoMClientLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: client
Source: "..\dist\MoMServerManager.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: server

[Types]
Name: "full"; Description: "Client and dedicated server"
Name: "clientonly"; Description: "Client only"
Name: "serveronly"; Description: "Dedicated server only"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "client"; Description: "Client: reversible patch and EAC-free launcher"; Types: full clientonly
Name: "server"; Description: "Server: replacement backend and management panel"; Types: full serveronly

[Icons]
Name: "{group}\MoM Revival Client"; Filename: "{app}\{#MyAppExeName}"; Components: client
Name: "{group}\Server Manager"; Filename: "{app}\MoMServerManager.exe"; Components: server
Name: "{autodesktop}\MoM Revival Client"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Components: client
Name: "{autodesktop}\MoM Server Manager"; Filename: "{app}\MoMServerManager.exe"; Tasks: managerdesktopicon; Components: server

[Tasks]
Name: "desktopicon"; Description: "Create a client desktop shortcut"; GroupDescription: "Shortcuts:"; Components: client
Name: "managerdesktopicon"; Description: "Create a server manager desktop shortcut"; GroupDescription: "Shortcuts:"; Components: server

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Configure the client"; Flags: nowait postinstall skipifsilent shellexec; Components: client
Filename: "{app}\MoMServerManager.exe"; Description: "Open the server manager"; Flags: nowait postinstall skipifsilent shellexec unchecked; Components: server
