[Setup]
AppName=Rust AutoConnect
AppVersion=0.2.0
DefaultDirName={autopf}\RustAutoConnect
DefaultGroupName=Rust AutoConnect
UninstallDisplayIcon={app}\RustAutoConnect.exe
Compression=lzma2
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=RustAutoConnect_Setup_v0.2.0

[Files]
Source: "dist\RustAutoConnect.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Rust AutoConnect"; Filename: "{app}\RustAutoConnect.exe"
Name: "{group}\Uninstall Rust AutoConnect"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Rust AutoConnect"; Filename: "{app}\RustAutoConnect.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\RustAutoConnect.exe"; Description: "Launch Rust AutoConnect"; Flags: nowait postinstall skipifsilent
