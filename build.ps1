param(
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'
$venv = Join-Path $PSScriptRoot '.venv'
$projectPython = Join-Path $venv 'Scripts\python.exe'

function Invoke-Python {
    param([string]$Executable, [string[]]$Arguments)

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $projectPython -PathType Leaf)) {
    if ($PythonPath) {
        Invoke-Python -Executable $PythonPath -Arguments @('-m', 'venv', $venv)
    } elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
        Invoke-Python -Executable 'py.exe' -Arguments @('-3.12', '-m', 'venv', $venv)
    } else {
        Invoke-Python -Executable 'python.exe' -Arguments @('-m', 'venv', $venv)
    }
}

Invoke-Python -Executable $projectPython -Arguments @(
    '-m', 'pip', 'install', '-r', (Join-Path $PSScriptRoot 'requirements.txt')
)

$dist = Join-Path $PSScriptRoot 'dist'
$build = Join-Path $PSScriptRoot 'build'
New-Item -Path $build -ItemType Directory -Force | Out-Null
Invoke-Python -Executable $projectPython -Arguments @(
    '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed', '--name', 'MouseActivity',
    '--icon', (Join-Path $PSScriptRoot 'assets\MouseActivity.ico'),
    '--distpath', $dist, '--workpath', $build, '--specpath', $build,
    (Join-Path $PSScriptRoot 'MouseActivity.py')
)

Get-Item -LiteralPath (Join-Path $dist 'MouseActivity.exe')
