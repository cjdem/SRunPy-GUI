#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDirectory
  #define SourceDirectory "..\release\build\SRunClient.dist"
#endif
#ifndef OutputDirectory
  #define OutputDirectory "..\release"
#endif

#define AppName "SRunPy 校园网登录器"
#define AppPublisher "cjdem"
#define AppExecutable "SRunClient.exe"
#define AppId "{{BC973ECE-31D9-4BC8-B179-1DF8BB02F462}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/cjdem/SRunPy-GUI
AppSupportURL=https://github.com/cjdem/SRunPy-GUI/issues
DefaultDirName={localappdata}\Programs\SRunPy
DefaultGroupName=SRunPy
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDirectory}
OutputBaseFilename=SRunPy-{#AppVersion}-win-x64-setup
SetupIconFile=..\srunpy\html\icons\logo.ico
UninstallDisplayIcon={app}\{#AppExecutable}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "{#SourceDirectory}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SRunPy 校园网登录器"; Filename: "{app}\{#AppExecutable}"
Name: "{autodesktop}\SRunPy 校园网登录器"; Filename: "{app}\{#AppExecutable}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExecutable}"; Description: "启动 SRunPy 校园网登录器"; Flags: nowait postinstall skipifsilent

[Code]
function WebView2RuntimeInstalled(): Boolean;
begin
  Result :=
    DirExists(ExpandConstant('{pf32}\Microsoft\EdgeWebView\Application')) or
    DirExists(ExpandConstant('{localappdata}\Microsoft\EdgeWebView\Application'));
end;

procedure CurStepChanged(CurrentStep: TSetupStep);
begin
  if (CurrentStep = ssPostInstall) and (not WebView2RuntimeInstalled()) then
  begin
    MsgBox(
      '未检测到 Microsoft Edge WebView2 Runtime。若客户端无法启动，请从 Microsoft 官方网站安装 WebView2 Evergreen Runtime。',
      mbInformation,
      MB_OK
    );
  end;
end;
