; Machete Charts - Inno Setup Installer Script
; Compile with Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
;
; To build: Open this file in Inno Setup Compiler and click Build > Compile
; Output: installer/Output/MacheteChartsSetup.exe

#define MyAppName "Machete Charts"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "hermes-tv.com"
#define MyAppURL "https://hermes-tv.com"

[Setup]
AppId={{8F2A3B7E-4C5D-6E8F-9A1B-2C3D4E5F6789}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={code:GetCommunityFolder}
DirExistsWarning=no
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=MacheteChartsSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
Uninstallable=yes
UninstallDisplayName={#MyAppName}
; No admin rights needed - Community folder is in user space
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
SelectDirLabel3=Setup will install {#MyAppName} into the following MSFS Community folder.
SelectDirBrowseLabel=If this is not correct, click Browse to select your Community folder.

[Files]
; Plugin files
Source: "..\machete-charts\manifest.json"; DestDir: "{app}\machete-charts"; Flags: ignoreversion
Source: "..\machete-charts\layout.json"; DestDir: "{app}\machete-charts"; Flags: ignoreversion
Source: "..\machete-charts\InGamePanels\*"; DestDir: "{app}\machete-charts\InGamePanels"; Flags: ignoreversion recursesubdirs
Source: "..\machete-charts\html_ui\*"; DestDir: "{app}\machete-charts\html_ui"; Flags: ignoreversion recursesubdirs

[UninstallDelete]
Type: filesandordirs; Name: "{app}\machete-charts"

[Code]
// Auto-detect MSFS Community folder
function GetCommunityFolder(Param: String): String;
var
  Path: String;
  CfgFile: String;
  CfgLines: TArrayOfString;
  I: Integer;
  Line: String;
  P: Integer;
begin
  // Try MSFS 2024 (MS Store)
  Path := ExpandConstant('{localappdata}') + '\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community';
  if DirExists(Path) then begin
    Result := Path;
    Exit;
  end;

  // Try MSFS 2020 (MS Store)
  Path := ExpandConstant('{localappdata}') + '\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache\Packages\Community';
  if DirExists(Path) then begin
    Result := Path;
    Exit;
  end;

  // Try MSFS 2020 (Steam)
  Path := ExpandConstant('{userappdata}') + '\Microsoft Flight Simulator\Packages\Community';
  if DirExists(Path) then begin
    Result := Path;
    Exit;
  end;

  // Try MSFS 2024 (Steam)
  Path := ExpandConstant('{userappdata}') + '\Microsoft Flight Simulator 2024\Packages\Community';
  if DirExists(Path) then begin
    Result := Path;
    Exit;
  end;

  // Try reading UserCfg.opt for custom paths
  CfgFile := ExpandConstant('{localappdata}') + '\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache\UserCfg.opt';
  if not FileExists(CfgFile) then
    CfgFile := ExpandConstant('{userappdata}') + '\Microsoft Flight Simulator\UserCfg.opt';
  if not FileExists(CfgFile) then
    CfgFile := ExpandConstant('{localappdata}') + '\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\UserCfg.opt';

  if FileExists(CfgFile) then begin
    if LoadStringsFromFile(CfgFile, CfgLines) then begin
      for I := 0 to GetArrayLength(CfgLines) - 1 do begin
        Line := CfgLines[I];
        P := Pos('InstalledPackagesPath', Line);
        if P > 0 then begin
          P := Pos('"', Line);
          if P > 0 then begin
            Line := Copy(Line, P + 1, Length(Line));
            P := Pos('"', Line);
            if P > 0 then begin
              Path := Copy(Line, 1, P - 1) + '\Community';
              if DirExists(Path) then begin
                Result := Path;
                Exit;
              end;
            end;
          end;
        end;
      end;
    end;
  end;

  // Fallback
  Result := ExpandConstant('{userappdata}') + '\Microsoft Flight Simulator\Packages\Community';
end;
