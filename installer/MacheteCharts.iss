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
// Extract Community path from a UserCfg.opt file
function GetCommunityFromCfg(CfgFile: String): String;
var
  CfgLines: TArrayOfString;
  I, P: Integer;
  Line, Path: String;
begin
  Result := '';
  if FileExists(CfgFile) then begin
    if LoadStringsFromFile(CfgFile, CfgLines) then begin
      for I := 0 to GetArrayLength(CfgLines) - 1 do begin
        Line := CfgLines[I];
        if Pos('InstalledPackagesPath', Line) > 0 then begin
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
end;

// Normalize a path for comparison (lowercase, no trailing backslash)
function NormPath(Path: String): String;
begin
  Result := Lowercase(RemoveBackslashUnlessRoot(Path));
end;

// Add a path to the list if it's not already present
procedure AddIfNew(List: TStringList; Path: String);
var
  I: Integer;
  Normalized: String;
begin
  Normalized := NormPath(Path);
  for I := 0 to List.Count - 1 do begin
    if NormPath(List[I]) = Normalized then
      Exit;
  end;
  List.Add(Path);
end;

// Find all MSFS Community folders (standard paths + UserCfg.opt custom paths)
function FindAllCommunityFolders(): TStringList;
var
  Path: String;
begin
  Result := TStringList.Create;

  // MSFS 2024 (MS Store)
  Path := ExpandConstant('{localappdata}') + '\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community';
  if DirExists(Path) then AddIfNew(Result, Path);

  // MSFS 2020 (MS Store)
  Path := ExpandConstant('{localappdata}') + '\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache\Packages\Community';
  if DirExists(Path) then AddIfNew(Result, Path);

  // MSFS 2020 (Steam)
  Path := ExpandConstant('{userappdata}') + '\Microsoft Flight Simulator\Packages\Community';
  if DirExists(Path) then AddIfNew(Result, Path);

  // MSFS 2024 (Steam)
  Path := ExpandConstant('{userappdata}') + '\Microsoft Flight Simulator 2024\Packages\Community';
  if DirExists(Path) then AddIfNew(Result, Path);

  // UserCfg.opt custom paths
  Path := GetCommunityFromCfg(ExpandConstant('{localappdata}') + '\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\UserCfg.opt');
  if Path <> '' then AddIfNew(Result, Path);

  Path := GetCommunityFromCfg(ExpandConstant('{localappdata}') + '\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache\UserCfg.opt');
  if Path <> '' then AddIfNew(Result, Path);

  Path := GetCommunityFromCfg(ExpandConstant('{userappdata}') + '\Microsoft Flight Simulator\UserCfg.opt');
  if Path <> '' then AddIfNew(Result, Path);

  Path := GetCommunityFromCfg(ExpandConstant('{userappdata}') + '\Microsoft Flight Simulator 2024\UserCfg.opt');
  if Path <> '' then AddIfNew(Result, Path);
end;

// Auto-detect primary MSFS Community folder (first found)
function GetCommunityFolder(Param: String): String;
var
  AllFolders: TStringList;
begin
  AllFolders := FindAllCommunityFolders;
  try
    if AllFolders.Count > 0 then
      Result := AllFolders[0]
    else
      Result := ExpandConstant('{userappdata}') + '\Microsoft Flight Simulator\Packages\Community';
  finally
    AllFolders.Free;
  end;
end;

// Show all target directories on the "Ready to Install" page
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  AllFolders: TStringList;
  PrimaryDir: String;
  I: Integer;
  HasAdditional: Boolean;
begin
  Result := MemoDirInfo + NewLine;

  AllFolders := FindAllCommunityFolders;
  try
    PrimaryDir := NormPath(WizardDirValue);
    HasAdditional := False;
    for I := 0 to AllFolders.Count - 1 do begin
      if NormPath(AllFolders[I]) <> PrimaryDir then begin
        if not HasAdditional then begin
          Result := Result + NewLine + Space + 'Additional MSFS installations detected:' + NewLine;
          HasAdditional := True;
        end;
        Result := Result + Space + Space + AllFolders[I] + NewLine;
      end;
    end;
  finally
    AllFolders.Free;
  end;
end;

// After install, copy to all additional Community folders
procedure CurStepChanged(CurStep: TSetupStep);
var
  AllFolders: TStringList;
  PrimaryDir, SrcDir, DestDir: String;
  I, ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    AllFolders := FindAllCommunityFolders;
    try
      PrimaryDir := NormPath(WizardDirValue);
      SrcDir := WizardDirValue + '\machete-charts';
      for I := 0 to AllFolders.Count - 1 do begin
        if NormPath(AllFolders[I]) <> PrimaryDir then begin
          DestDir := AllFolders[I] + '\machete-charts';
          Exec('cmd.exe', '/c xcopy /E /I /Y "' + SrcDir + '" "' + DestDir + '"',
            '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        end;
      end;
    finally
      AllFolders.Free;
    end;
  end;
end;

// On uninstall, remove from all Community folders
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AllFolders: TStringList;
  TargetDir: String;
  I: Integer;
begin
  if CurUninstallStep = usPostUninstall then begin
    AllFolders := FindAllCommunityFolders;
    try
      for I := 0 to AllFolders.Count - 1 do begin
        TargetDir := AllFolders[I] + '\machete-charts';
        if DirExists(TargetDir) then
          DelTree(TargetDir, True, True, True);
      end;
    finally
      AllFolders.Free;
    end;
  end;
end;
