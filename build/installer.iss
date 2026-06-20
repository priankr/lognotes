; Inno Setup script for the legacy Tk LogNotes app.
; Superseded by the Electron build (electron-builder NSIS). Kept locally for
; reference; not part of the shipped product.
; Build with: iscc build\installer.iss
; Output:     build\Output\LogNotes-tk-Setup-<version>.exe

#define MyAppName "LogNotes (Tk)"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Priank Ravichandar"
#define MyAppExeName "LogNotes-tk.exe"

[Setup]
AppId={{7A3F2C54-9E4B-4D12-8B6A-LOGNOTESAPP001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\LogNotes-tk
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=LogNotes-tk-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Do NOT require admin — app writes to %APPDATA% and %LOCALAPPDATA%.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=..\src\ui\assets\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\LogNotes-tk\LogNotes-tk.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\LogNotes-tk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\src\ui\assets\logo.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\src\ui\assets\logo.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

; User data in %APPDATA%\LogNotes and cache in %LOCALAPPDATA%\LogNotes
; are intentionally left in place on uninstall (standard practice).
