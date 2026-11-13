; 연구보안 등급분류 분류기준(고시) 검토(1.3.2부터, 옛 이름: 고시 수준 검토) 설치 파일 스크립트(Inno Setup 6). 프로그램 폴더에서 build_exe.bat이 부른다.
; 입력: dist\고시판정v1\ (PyInstaller 폴더형 빌드). 출력: dist\연구보안등급분류_분류기준고시검토_설치_v1.4.2.exe
; 사용자 폴더에 설치(관리자 권한 불필요). 결정 0012(고시판정은 설치 파일로 배포).
; 만든 사람 표시(1.3.0): 설치 화면 모든 쪽 아래 줄(BeveledLabel)과 설치 정보의 게시자·연락처에만 둔다.

#define AppName "연구보안 등급분류 분류기준(고시) 검토"
; 1.3.1까지의 이름. 덮어 설치 때 이 이름의 바로가기·시작 메뉴 묶음만 지운다([InstallDelete]).
#define OldAppName "고시 수준 검토"
#define AppVersion "1.4.2"
#define AppExe "고시판정v1.exe"

[Setup]
; AppId는 바꾸지 않는다(바꾸면 업데이트 설치가 다른 프로그램으로 등록된다).
AppId={{6F3C2A51-9B7E-4D6A-8E21-0C4B7F9D1A35}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=min
AppContact=min@kistep.re.kr
; 새로 설치할 때의 폴더. 이미 설치한 PC는 전의 설치 폴더(…\Programs\고시수준검토)를 그대로 쓴다(UsePreviousAppDir 기본값).
DefaultDirName={localappdata}\Programs\연구보안등급분류_분류기준고시검토
DefaultGroupName={#AppName}
; 시작 메뉴 묶음은 전의 이름을 물려받지 않고 새 이름을 쓴다.
UsePreviousGroup=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
OutputDir=..\dist
OutputBaseFilename=연구보안등급분류_분류기준고시검토_설치_v{#AppVersion}
SetupIconFile=..\resources\book_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Messages]
BeveledLabel=powered by min · min@kistep.re.kr

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "바로가기:"; Flags: unchecked

[InstallDelete]
; 덮어 설치: 옛 이름 바로가기 둘과 바탕화면 바로가기만 지우고, 비어 있으면 옛 묶음 폴더를 지운다. 없으면 그냥 넘어간다.
Type: files; Name: "{autoprograms}\{#OldAppName}\{#OldAppName}.lnk"
Type: files; Name: "{autoprograms}\{#OldAppName}\{#OldAppName} 제거.lnk"
Type: dirifempty; Name: "{autoprograms}\{#OldAppName}"
Type: files; Name: "{autodesktop}\{#OldAppName}.lnk"

[Files]
Source: "..\dist\고시판정v1\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 프로그램 폴더 안에 실행 중 생긴 파일(파이썬 캐시 등)까지 지운다. 결과 파일은 사용자가 고른 다른 곳에 있으므로 지워지지 않는다.
Type: filesandordirs; Name: "{app}"
