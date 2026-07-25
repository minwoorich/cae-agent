<#
.SYNOPSIS
Windows에서 CAE Agent용 Python 가상환경과 초기 설정을 안전하게 준비합니다.

.DESCRIPTION
이 스크립트는 저장소 내부에만 가상환경과 설정 파일을 만듭니다. Python, Codex
CLI, Ansys 같은 시스템 프로그램은 자동 설치하지 않으며, 누락된 항목은 마지막
doctor 결과와 안내 메시지로 구분합니다. 같은 명령을 반복해도 기존 가상환경과
cae-agent.toml을 삭제하거나 덮어쓰지 않습니다.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$WithAnsys,
    [switch]$WithDev,
    [string]$PythonExecutable,
    [string]$VirtualEnvironment = ".venv",
    [switch]$SkipPipUpgrade
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Windows PowerShell 5.1의 기본 코드페이지에서는 하위 Python 프로세스가 출력한
# 한국어가 깨질 수 있으므로 현재 프로세스와 파이프의 인코딩을 UTF-8로 통일한다.
$utf8Encoding = [Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8Encoding
[Console]::OutputEncoding = $utf8Encoding
$global:OutputEncoding = $utf8Encoding

function Write-Step {
    param([string]$Message)
    Write-Host "[CAE Agent] $Message" -ForegroundColor Cyan
}

function Resolve-PythonExecutable {
    param([string]$RequestedExecutable)

    if ($RequestedExecutable) {
        $command = Get-Command $RequestedExecutable -ErrorAction SilentlyContinue
        if (-not $command) {
            throw "지정한 Python 실행 파일을 찾을 수 없습니다: $RequestedExecutable"
        }
        return $command.Source
    }

    # Windows Python Launcher가 있으면 실제 Python 경로를 먼저 물어본다. `py`
    # 자체는 Python 인터프리터가 아니므로 가상환경 생성 이후 재사용할 수 없다.
    $launcher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($launcher) {
        $resolved = & $launcher.Source -3 -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -eq 0 -and $resolved) {
            return $resolved.Trim()
        }
    }

    $python = Get-Command "python" -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }
    throw @"
Python 3.11 이상을 찾지 못했습니다.
Python을 공식 배포처에서 설치한 뒤 새 PowerShell을 열고 다시 실행하세요.
이 스크립트는 사용자 동의 없이 시스템 Python을 자동 설치하지 않습니다.
"@
}

function Assert-SupportedPython {
    param([string]$Executable)

    $versionText = & $Executable -c (
        "import sys; print('{0}.{1}.{2}'.format(*sys.version_info[:3]))"
    )
    if ($LASTEXITCODE -ne 0 -or -not $versionText) {
        throw "Python 버전을 확인하지 못했습니다: $Executable"
    }
    $version = [version]$versionText.Trim()
    if ($version -lt [version]"3.11.0") {
        throw "Python 3.11 이상이 필요합니다. 발견된 버전: $version"
    }
    Write-Step "Python $version 사용: $Executable"
}

if ($env:OS -ne "Windows_NT") {
    throw "setup.ps1은 Windows 전용 설치 스크립트입니다."
}

$repositoryRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$venvPath = if ([IO.Path]::IsPathRooted($VirtualEnvironment)) {
    [IO.Path]::GetFullPath($VirtualEnvironment)
} else {
    [IO.Path]::GetFullPath((Join-Path $repositoryRoot $VirtualEnvironment))
}
$repositoryPrefix = $repositoryRoot.TrimEnd(
    [IO.Path]::DirectorySeparatorChar
) + [IO.Path]::DirectorySeparatorChar
if (-not $venvPath.StartsWith(
    $repositoryPrefix,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "가상환경 경로는 저장소 내부여야 합니다: $venvPath"
}

$python = Resolve-PythonExecutable $PythonExecutable
Assert-SupportedPython $python

$extras = @()
if ($WithAnsys) {
    $extras += "ansys"
}
if ($WithDev) {
    $extras += "dev"
}
$packageTarget = if ($extras.Count -gt 0) {
    ".[" + ($extras -join ",") + "]"
} else {
    "."
}

$configPath = Join-Path $repositoryRoot "cae-agent.toml"
$exampleConfig = Join-Path $repositoryRoot "cae-agent.example.toml"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if ($WhatIfPreference) {
    Write-Step "검증 전용 모드이므로 파일과 패키지를 변경하지 않습니다."
    Write-Host "  가상환경: $venvPath"
    Write-Host "  설치 대상: $packageTarget"
    Write-Host "  초기 설정: $configPath"
    Write-Host "  설치 후 진단: cae-agent doctor"
    return
}

if (Test-Path -LiteralPath $venvPath) {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw @"
기존 경로가 올바른 Python 가상환경이 아닙니다: $venvPath
데이터 보호를 위해 자동 삭제하지 않습니다. 경로를 직접 확인하거나
-VirtualEnvironment 옵션으로 저장소 내부의 다른 경로를 지정하세요.
"@
    }
    Write-Step "기존 가상환경을 그대로 재사용합니다: $venvPath"
} elseif ($PSCmdlet.ShouldProcess($venvPath, "Python 가상환경 생성")) {
    Write-Step "Python 가상환경을 생성합니다: $venvPath"
    & $python -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Python 가상환경 생성에 실패했습니다."
    }
}

if (-not $SkipPipUpgrade) {
    Write-Step "가상환경의 pip를 업그레이드합니다."
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "pip 업그레이드에 실패했습니다."
    }
}

Write-Step "CAE Agent 패키지를 설치합니다: $packageTarget"
Push-Location $repositoryRoot
try {
    & $venvPython -m pip install -e $packageTarget
    if ($LASTEXITCODE -ne 0) {
        throw "CAE Agent 패키지 설치에 실패했습니다."
    }
} finally {
    Pop-Location
}

if (Test-Path -LiteralPath $configPath) {
    Write-Step "기존 설정 파일을 보존합니다: $configPath"
} else {
    Write-Step "예제 설정을 초기 설정 파일로 복사합니다."
    Copy-Item -LiteralPath $exampleConfig -Destination $configPath
}

$codex = Get-Command "codex" -ErrorAction SilentlyContinue
if ($codex) {
    Write-Step "Codex CLI를 찾았습니다. 기존 로그인 정보를 그대로 사용합니다."
} else {
    Write-Warning @"
Codex CLI가 설치되어 있지 않습니다. 기본 설치는 완료됐지만 AI 생성 기능은
사용할 수 없습니다. Codex CLI를 별도로 설치하고 로그인한 뒤 doctor를 다시
실행하세요. 이 스크립트는 인증정보를 요청하거나 저장하지 않습니다.
"@
}

Write-Step "최종 환경 진단을 실행합니다."
& $venvPython -m cae_agent doctor
$doctorExitCode = $LASTEXITCODE
if ($doctorExitCode -ne 0) {
    Write-Warning @"
기본 설치는 끝났지만 필수 진단 항목이 남아 있습니다.
위 FAIL 항목의 Python, Git 또는 Ansys 설치 안내를 확인하세요. 특히 Ansys는
별도 설치와 라이선스가 필요하며 이 스크립트가 자동 설치하지 않습니다.
"@
    exit $doctorExitCode
}

Write-Step "설치와 환경 진단이 모두 완료됐습니다."
