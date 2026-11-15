; Programme d'installation Windows (Inno Setup 6)
; Compiler avec packaging\construire.ps1, ou :
;   ISCC.exe packaging\installateur.iss
; L'application doit d'abord être construite dans build\dist\PlanificateurEtudes (PyInstaller).

#define NomApp "Planificateur d'études"
#define Version "0.4.3"
#define Exe "PlanificateurEtudes.exe"

[Setup]
AppId={{6F2C1E5A-9B7D-4E0A-8C1B-2D3F4A5B6C7D}
AppName={#NomApp}
AppVersion={#Version}
AppVerName={#NomApp} {#Version}
AppPublisher=Abdoul Aziz
VersionInfoVersion={#Version}
VersionInfoDescription=Installation de {#NomApp}
; Installation pour l'utilisateur courant : aucun droit administrateur nécessaire
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\PlanificateurEtudes
DefaultGroupName={#NomApp}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\installateur
OutputBaseFilename=Installer-PlanificateurEtudes-{#Version}
SetupIconFile=icone.ico
UninstallDisplayIcon={app}\{#Exe}
UninstallDisplayName={#NomApp}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "bureau"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "..\build\dist\PlanificateurEtudes\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#NomApp}"; Filename: "{app}\{#Exe}"
Name: "{autodesktop}\{#NomApp}"; Filename: "{app}\{#Exe}"; Tasks: bureau

[Run]
Filename: "{app}\{#Exe}"; Description: "Lancer {#NomApp}"; Flags: nowait postinstall skipifsilent

[Messages]
fr.FinishedLabel=L'installation de [name] est terminée.%n%nVos données sont enregistrées dans votre dossier personnel (%APPDATA%\PlanificateurEtudes) : une désinstallation ou une mise à jour ne les supprime jamais.
