param([Parameter(Mandatory=$true)][string]$CaseId, [Parameter(Mandatory=$true)][string]$EvidenceDir)
$ErrorActionPreference = 'Continue'
$recorder = Join-Path $EvidenceDir 'recorder'
New-Item -ItemType Directory -Force -Path $recorder | Out-Null
$videoRef = 'video/capture.mkv'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$fixtureOnly = @('S11-POLICY-WEB', 'S11-MACOS-DEFAULT-BRAND-IDENTITY', 'S11-CONTRAST-BOUNDARY-INJECTION',
    'S11-HIGH-CONTRAST-IGNORES-SYSTEM', 'S11-SYSTEM-UNAVAILABLE-RESOLVES-BRAND') -contains $CaseId
$selectionPath = Join-Path $recorder 'accent-selection.txt'
if ($fixtureOnly) {
    'No OS setting change is required for this page fixture.' | Set-Content -Encoding UTF8 $selectionPath
    $selectionExit = 0
} else {
    try {
        & pwsh -NoProfile -ExecutionPolicy Bypass -File automation/accent/windows-select-accent.ps1 -AccentName 'Purple' 2>&1 |
            Out-String | Set-Content -Encoding UTF8 $selectionPath
        $selectionExit = $LASTEXITCODE
    } catch {
        $_ | Out-String | Set-Content -Encoding UTF8 $selectionPath
        $selectionExit = 1
    }
}

$readbackPath = Join-Path $recorder 'native-readback.json'
$readbackExe = $env:SHELL_WINDOWS_READBACK_EXE
if ($fixtureOnly) {
    '{}' | Set-Content -Encoding UTF8 $readbackPath
    $readbackExit = 0
} elseif ($readbackExe -and (Test-Path $readbackExe)) {
    & $readbackExe 2>&1 | Out-String | Set-Content -Encoding UTF8 $readbackPath
    $readbackExit = $LASTEXITCODE
} else {
    'Independent UISettings readback executable was not supplied by the runner.' | Set-Content -Encoding UTF8 $readbackPath
    $readbackExit = 127
}
$screenBounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$screenBitmap = New-Object System.Drawing.Bitmap($screenBounds.Width, $screenBounds.Height)
$screenGraphics = [System.Drawing.Graphics]::FromImage($screenBitmap)
$screenGraphics.CopyFromScreen($screenBounds.Location, [System.Drawing.Point]::Empty, $screenBounds.Size)
$screenBitmap.Save((Join-Path $recorder 'screen.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$screenGraphics.Dispose(); $screenBitmap.Dispose()

$eventPath = Join-Path $EvidenceDir 'events.jsonl'
$rows = @()
if (Test-Path $eventPath) {
    foreach ($line in Get-Content $eventPath) {
        try { $row = $line | ConvertFrom-Json; if ($row.hostPid -eq [int]$env:SHELL_APP_PID) { $rows += $row } } catch {}
    }
}
function Get-Fields($Row) { if ($Row.fields -is [System.Management.Automation.PSCustomObject]) { return $Row.fields }; return $Row }
function Get-EventName($Row) { if ($Row.name) { return $Row.name }; if ($Row.fields.name) { return $Row.fields.name }; return $Row.event }
$native = @($rows | Where-Object { (Get-EventName $_) -eq 's11.native-event' })
$updates = @($rows | Where-Object { (Get-EventName $_) -eq 's11.host-and-token-update' })
$frames = @($rows | Where-Object { (Get-Fields $_).phase -eq 'tokens-mutated' })
$sequences = @($native | ForEach-Object { [string](Get-Fields $_).sequence })
$correlated = @($updates | Where-Object { $sequences -contains [string](Get-Fields $_).sequence })
$readyEvents = @('s11.listener-ready', 's11.platform-policy', 's11.clamp-result', 's11.high-contrast-ignored-system')
$ready = [bool]($rows | Where-Object { $readyEvents -contains (Get-EventName $_) } | Select-Object -First 1)
$readerReady = [bool]($rows | Where-Object { (Get-EventName $_) -eq 's11.reader-ready' } | Select-Object -First 1)
$initial = $rows | Where-Object { (Get-EventName $_) -eq 's11.initial-reader-snapshot' } | Select-Object -First 1
$hostRgb = if ($initial) { (Get-Fields $initial).rgb } else { $null }
$readRgb = $null
try { $readRgb = (Get-Content $readbackPath -Raw | ConvertFrom-Json).rgb } catch {}
$readbackMatches = $false
if ($hostRgb -and $readRgb -and $hostRgb.Count -eq 3 -and $readRgb.Count -eq 3) {
    $diffs = for ($index = 0; $index -lt 3; $index++) { [math]::Abs([double]$hostRgb[$index] - [double]$readRgb[$index]) }
    $readbackMatches = (($diffs | Measure-Object -Maximum).Maximum -le (1.0 / 255.0))
}

$caseFile = Get-Content 'cases/s11.json' -Raw | ConvertFrom-Json
$case = $caseFile.cases | Where-Object { $_.id -eq $CaseId } | Select-Object -First 1
$assertions = @{}
foreach ($item in $case.assertions) {
    $suffix = $item.id
    $verdict = 'UNVERIFIED'
    $actual = 'Native preference/readback was attempted; synchronized event and presentation evidence is incomplete.'
    $refs = @('recorder/accent-selection.txt', 'recorder/native-readback.json')
    if ($suffix -match 'READBACK') {
        $verdict = if ($selectionExit -eq 0 -and $readbackExit -eq 0 -and $readerReady -and $readbackMatches) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "Independent and host sRGB readback agree within 1/255=$readbackMatches; reader ready=$readerReady."
        $refs = @('recorder/accent-selection.txt', 'recorder/native-readback.json', 'events.jsonl')
    } elseif ($suffix -match 'EVENT') {
        $verdict = if ($native.Count -gt 0 -and $correlated.Count -gt 0) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "Native events=$($native.Count); sequence-matched host updates=$($correlated.Count)."
        $refs = @('events.jsonl', $videoRef)
    } elseif ($suffix -match 'FRAME') {
        $verdict = 'UNVERIFIED'
        $actual = "Renderer frame markers=$($frames.Count); the first presented frame still requires capture-index correlation."
        $refs = @('events.jsonl', $videoRef)
    } elseif ($suffix -match 'UPDATE') {
        $reloadFalse = $correlated.Count -eq 1 -and (Get-Fields $correlated[0]).reload -eq $false
        $verdict = if ($native.Count -eq 1 -and $correlated.Count -eq 1 -and $reloadFalse) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "Native changes=$($native.Count); sequence-matched host updates=$($correlated.Count); reload=false required."
        $refs = @('events.jsonl', $videoRef)
    } elseif ($CaseId -eq 'S11-CONTRAST-BOUNDARY-INJECTION' -and $item.id -eq 'S11-CONTRAST-CLAMP') {
        $clamp = $rows | Where-Object { (Get-EventName $_) -eq 's11.clamp-result' } | Select-Object -First 1
        $clamped = $clamp -and ((Get-Fields $clamp).clamped -eq $true -or (Get-Fields $clamp).clampTarget -ne 'none')
        $verdict = if ($clamped) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "Synthetic boundary injection clamp outcome observed=$clamped; it does not prove native delivery."
        $refs = @('events.jsonl')
    } elseif ($CaseId -eq 'S11-CONTRAST-BOUNDARY-INJECTION' -and $item.id -eq 'S11-CONTRAST-NATIVE') {
        $boundary = $rows | Where-Object { (Get-EventName $_) -eq 's11.boundary-injection' } | Select-Object -First 1
        $nonNative = $boundary -and (Get-Fields $boundary).nativeEvent -eq $false
        $verdict = if ($nonNative) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "Boundary sample is explicitly non-native=$nonNative."
        $refs = @('events.jsonl')
    } elseif ($CaseId -eq 'S11-HIGH-CONTRAST-IGNORES-SYSTEM' -and $item.id -eq 'S11-HIGH-CONTRAST-IGNORED') {
        $sample = $rows | Where-Object { (Get-EventName $_) -eq 's11.high-contrast-ignored-system' } | Select-Object -First 1
        $ignored = $sample -and (Get-Fields $sample).resolvedSource -eq 'high-contrast-theme'
        $verdict = if ($ignored) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "High-contrast preview resolved independently of System=$ignored."
        $refs = @('events.jsonl', $videoRef)
    } elseif ($CaseId -eq 'S11-POLICY-WEB' -and $item.id -eq 'S11-POLICY-WEB-HIDDEN') {
        $policy = $rows | Where-Object { (Get-EventName $_) -eq 's11.platform-policy' } | Select-Object -First 1
        $hidden = $policy -and (Get-Fields $policy).platform -eq 'web' -and (Get-Fields $policy).systemVisible -eq $false
        $verdict = if ($hidden) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "Web policy fixture hid System without a native read=$hidden."
        $refs = @('events.jsonl', $videoRef)
    } elseif ($CaseId -eq 'S11-SYSTEM-UNAVAILABLE-RESOLVES-BRAND' -and $item.id -eq 'S11-SYSTEM-UNAVAILABLE-BRAND') {
        $verdict = 'UNVERIFIED'
        $actual = 'System hidden/brand fallback selected; a visible page and event capture are required to confirm it.'
        $refs = @('events.jsonl', $videoRef)
    } elseif ($suffix -match 'CLAMP') {
        $clamped = [bool]($rows | Where-Object { (Get-EventName $_) -eq 's11.host-and-token-update' -and ((Get-Fields $_).clamped -eq $true) } | Select-Object -First 1)
        $verdict = if ($clamped) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "Observed native updates with an applied contrast clamp=$clamped."
        $refs = @('recorder/native-readback.json', 'events.jsonl', 'recorder/screen.png', $videoRef)
    } elseif ($suffix -match 'FALLBACK|BRAND') {
        $actual = 'When the reader is unavailable, System is hidden and stored System resolves to the test brand colour.'
        $refs = @('events.jsonl', 'recorder/native-readback.json', $videoRef)
    }
    foreach ($requiredRef in @('environment.json', 'events.jsonl', 'recorder/screen.png', $videoRef, 'video/index.json')) {
        if ($refs -notcontains $requiredRef) { $refs += $requiredRef }
    }
    $assertions[$item.id] = @{ verdict = $verdict; actual = $actual; evidence = $refs }
}
@{
    caseId = $CaseId
    platform = 'windows'
    ready = $ready
    fallback = 'System hidden; stored System resolves to the test brand colour.'
    assertions = $assertions
} | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 (Join-Path $recorder 'observations.json')
if ($selectionExit -ne 0 -or $readbackExit -ne 0) { exit 1 }
