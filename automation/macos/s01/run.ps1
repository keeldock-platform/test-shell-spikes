$ErrorActionPreference = 'Stop'

# PowerShell entry point for the canonical macOS adapter. Native launch,
# XCTest interaction, recorder extraction, analysis, and serialization remain
# in run.sh so both entry points produce the same artifact contract.
$adapter = Join-Path $PSScriptRoot 'run.sh'
function Get-EvidenceRoot {
    if ($env:SHELL_EVIDENCE_DIR) { return $env:SHELL_EVIDENCE_DIR }
    if ($env:SHELL_SPIKES_ARTIFACT_DIR) { return $env:SHELL_SPIKES_ARTIFACT_DIR }
    return $null
}

function Ensure-ResultsEnvelope {
    $evidenceRoot = Get-EvidenceRoot
    if (-not $evidenceRoot) { return }
    $resultPath = Join-Path $evidenceRoot 'assertions.json'
    $valid = $false
    if (Test-Path -LiteralPath $resultPath -PathType Leaf) {
        try {
            $document = Get-Content -Raw -LiteralPath $resultPath | ConvertFrom-Json
            $valid = $null -ne $document.PSObject.Properties['results'] -and $null -ne $document.results
        } catch { $valid = $false }
    }
    if (-not $valid) {
        New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
        [System.IO.File]::WriteAllText(
            $resultPath,
            '{"results":[]}' + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false)
        )
    }
}

$exitCode = 2
try {
    $bash = Get-Command bash -ErrorAction SilentlyContinue
    if ($null -eq $bash) { throw 'bash is required for the macOS S01 adapter.' }
    & $bash.Source $adapter
    $exitCode = $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $exitCode = 2
} finally {
    Ensure-ResultsEnvelope
}
exit $exitCode
