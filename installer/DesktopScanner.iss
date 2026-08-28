; Inno Setup script for Desktop Scanner
; Build:  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\DesktopScanner.iss
; Output: installer\Output\DesktopScanner-Setup-<version>.exe
;
; Packages the PyInstaller one-dir build at dist\Desktop Scanner\ into a
; single self-contained installer. Per-user install by default (no admin /
; UAC prompt needed); the user can switch to an all-users install from the
; privileges dialog.

#define MyAppName "Desktop Scanner"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Manasij Mandal"
#define MyAppURL "https://github.com/manasijmandal1999/desktop-scanner"
#define MyAppExeName "Desktop Scanner.exe"
#define MyDistDir "..\dist\Desktop Scanner"

[Setup]
; A fresh, stable GUID identifying this application to the installer/uninstaller.
AppId={{7C4B2E9A-3D5F-4A81-9B2C-6E1F0A7D3C42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\Desktop Scanner
DefaultGroupName=Desktop Scanner
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=DesktopScanner-Setup-{#MyAppVersion}
SetupIconFile=..\clearscanner\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MyDistDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyDistDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
