param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'

$source = Join-Path $PSScriptRoot '..\automation\accent\windows-readback.cpp'
$source = [System.IO.Path]::GetFullPath($source)
$installer = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $installer)) { throw 'Visual Studio compiler discovery is unavailable.' }
$installation = & $installer -latest -products '*' -property installationPath
if (-not $installation) { throw 'No Visual Studio C++ toolchain was found.' }
$vcvars = Join-Path $installation 'VC\Auxiliary\Build\vcvars64.bat'
if (-not (Test-Path -LiteralPath $vcvars)) { throw 'The x64 C++ environment script is unavailable.' }
$parent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$command = 'call "' + $vcvars + '" >nul && cl.exe /nologo /EHsc /std:c++20 /permissive- /utf-8 "' + $source + '" /Fe:"' + $OutputPath + '"'
& $env:ComSpec /d /s /c $command
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) {
    throw "The independent UISettings readback build failed with exit code $LASTEXITCODE."
}
Write-Output $OutputPath
