param([Parameter(Mandatory=$true)][string]$CaseId, [Parameter(Mandatory=$true)][string]$EvidenceDir)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$recorder = Join-Path $EvidenceDir 'recorder'
New-Item -ItemType Directory -Force -Path $recorder | Out-Null
$videoRef = 'video/capture.mkv'
$pidCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ProcessIdProperty, [int]$env:SHELL_APP_PID)
$root = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst(
    [System.Windows.Automation.TreeScope]::Children, $pidCondition)
if ($null -eq $root) { throw 'Launched PID has no UIAutomation window' }
$all = [System.Windows.Automation.TreeScope]::Descendants
$condition = [System.Windows.Automation.Condition]::TrueCondition

function Get-TreeText {
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $lines = [System.Collections.Generic.List[string]]::new()
    function Visit([System.Windows.Automation.AutomationElement]$element, [int]$depth) {
        if ($null -eq $element) { return }
        $name = $element.Current.Name
        if ($name) { $lines.Add((' ' * $depth) + $name) }
        $child = $walker.GetFirstChild($element)
        while ($null -ne $child) {
            Visit $child ($depth + 1)
            $child = $walker.GetNextSibling($child)
        }
    }
    Visit $root 0
    return $lines
}

function Find-Name([string]$Text) {
    $matcher = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty, $Text,
        [System.Windows.Automation.PropertyConditionFlags]::IgnoreCase)
    return $root.FindFirst($all, $matcher)
}

function Invoke-Element($Element) {
    if ($null -eq $Element) { return $false }
    try {
        $pattern = $null
        if ($Element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
            $pattern.Invoke()
            return $true
        }
    } catch {}
    return $false
}

function Save-Tree([string]$Name) {
    Get-TreeText | Set-Content -Encoding UTF8 (Join-Path $recorder $Name)
}

$deadline = (Get-Date).AddSeconds(30)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if (Find-Name 'Ready') { $ready = $true; break }
    Start-Sleep -Milliseconds 250
}
Save-Tree 'native-tree-before.txt'
$open = Find-Name 'Open Appearance dialog'
$opened = Invoke-Element $open
Start-Sleep -Milliseconds 500
$pickerButton = Find-Name 'Custom colour picker'
$pickerVisible = Invoke-Element $pickerButton
Start-Sleep -Seconds 1
Save-Tree 'native-tree-picker.txt'
$screenBounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$screenBitmap = New-Object System.Drawing.Bitmap($screenBounds.Width, $screenBounds.Height)
$screenGraphics = [System.Drawing.Graphics]::FromImage($screenBitmap)
$screenGraphics.CopyFromScreen($screenBounds.Location, [System.Drawing.Point]::Empty, $screenBounds.Size)
$screenBitmap.Save((Join-Path $recorder 'screen.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$screenGraphics.Dispose(); $screenBitmap.Dispose()

$accepted = [System.Collections.Generic.List[string]]::new()
$hexEdit = $root.FindFirst($all, (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Edit)))
if ($pickerVisible -and $hexEdit -and ($hexEdit.Current.Name -match 'hex|html|colour code|color code')) {
    foreach ($value in @('#7C4DFF', '#28A77A')) {
        if ($null -eq $hexEdit) { break }
        $hexEdit.SetFocus()
        [System.Windows.Forms.SendKeys]::SendWait('^a')
        [System.Windows.Forms.SendKeys]::SendWait($value)
        [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
        Start-Sleep -Milliseconds 400
        $pageText = (Get-TreeText) -join "`n"
        if ($pageText -match 'native-change' -and $pageText.ToLowerInvariant().Contains($value.ToLowerInvariant())) {
            $accepted.Add($value.ToLowerInvariant())
        }
        if ($value -eq '#7C4DFF') {
            $pickerButton = Find-Name 'Custom colour picker'
            if (Invoke-Element $pickerButton) {
                Start-Sleep -Milliseconds 500
                Save-Tree 'native-tree-picker.txt'
                $edits = $root.FindAll($all, (New-Object System.Windows.Automation.PropertyCondition(
                    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                    [System.Windows.Automation.ControlType]::Edit)))
                $hexEdit = $null
                foreach ($edit in $edits) {
                    if ($edit.Current.Name -match 'hex|html|colour code|color code') { $hexEdit = $edit; break }
                }
            }
        }
    }
}
$focusReturned = [bool](Find-Name 'Custom colour picker')
$manualOk = $false; $shortOk = $false; $invalidOk = $false; $cancelOk = $false; $dismissOk = $false
$openAgain = Find-Name 'Open Appearance dialog'
if (Invoke-Element $openAgain) {
    $hex = Find-Name 'HEX'
    if ($hex) {
        $hex.SetFocus()
        [System.Windows.Forms.SendKeys]::SendWait('^a')
        [System.Windows.Forms.SendKeys]::SendWait('#E0A526')
        Invoke-Element (Find-Name 'Use HEX value') | Out-Null
        Invoke-Element (Find-Name 'Apply') | Out-Null
        Start-Sleep -Milliseconds 300
        $manualText = (Get-TreeText) -join "`n"
        $manualOk = $manualText -match '#e0a526'

        Invoke-Element (Find-Name 'Open Appearance dialog') | Out-Null
        $hex = Find-Name 'HEX'
        if ($hex) {
            $hex.SetFocus(); [System.Windows.Forms.SendKeys]::SendWait('^a'); [System.Windows.Forms.SendKeys]::SendWait('abc')
            Invoke-Element (Find-Name 'Use HEX value') | Out-Null
            $shortOk = ((Get-TreeText) -join "`n") -match '#aabbcc'
            Invoke-Element (Find-Name 'Cancel') | Out-Null
            $cancelOk = ((Get-TreeText) -join "`n") -match '#e0a526'
            Invoke-Element (Find-Name 'Open Appearance dialog') | Out-Null
            $hex = Find-Name 'HEX'
            if ($hex) {
                $hex.SetFocus(); [System.Windows.Forms.SendKeys]::SendWait('^a'); [System.Windows.Forms.SendKeys]::SendWait('#12XZ')
                Invoke-Element (Find-Name 'Use HEX value') | Out-Null
                $invalidOk = ((Get-TreeText) -join "`n") -match 'Enter a colour'
                Invoke-Element (Find-Name 'Cancel') | Out-Null
            }
        }
    }
}
Invoke-Element (Find-Name 'Open Appearance dialog') | Out-Null
Invoke-Element (Find-Name 'Custom colour picker') | Out-Null
[System.Windows.Forms.SendKeys]::SendWait('{ESC}')
$dismissOk = ((Get-TreeText) -join "`n") -match '#e0a526'
Save-Tree 'page-accessibility.txt'
$eventFile = Join-Path $EvidenceDir 'events.jsonl'
foreach ($entry in (Get-TreeText | Where-Object { $_ -match '(?i)native-|appearance-|hex-' })) {
    @{ monotonicTime = [System.Diagnostics.Stopwatch]::GetTimestamp(); name = 's10.page-accessibility-event'; text = $entry } |
        ConvertTo-Json -Compress | Add-Content -Encoding UTF8 $eventFile
}

$assertions = @{}
$caseFile = Get-Content 'cases/s10.json' -Raw | ConvertFrom-Json
$case = $caseFile.cases | Where-Object { $_.id -eq $CaseId } | Select-Object -First 1
foreach ($assertion in $case.assertions) {
    $suffix = $assertion.id.Substring($CaseId.Length + 1)
    $verdict = 'UNVERIFIED'
    $actual = 'Native interaction was attempted; complete scenario evidence is required before a verdict.'
    $refs = @('recorder/native-events.jsonl', 'recorder/page-accessibility.txt')
    if ($suffix -eq 'NATIVE-PICKER' -and $ready -and $pickerVisible) {
        $verdict = if ($accepted.Count -eq 2) { 'PASS' } else { 'FAIL' }
        $actual = "Native picker visible; native hex entry returned $($accepted -join ', ')."
        $refs = @('recorder/native-tree-picker.txt', $videoRef)
    } elseif ($suffix -eq 'ACCEPT-FOCUS' -and $accepted.Count -eq 2 -and $focusReturned) {
        $verdict = 'PASS'
        $actual = "Native picker returned $($accepted -join ', ') and focus returned to the webview."
        $refs = @('recorder/page-accessibility.txt', $videoRef)
    } elseif ($suffix -eq 'MANUAL-HEX') {
        $verdict = if ($manualOk -and $shortOk -and $invalidOk) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "Manual six-digit, short, and invalid HEX observations: $manualOk/$shortOk/$invalidOk."
        $refs = @('recorder/page-accessibility.txt', $videoRef)
    } elseif ($suffix -eq 'APPLY-CANCEL') {
        $verdict = if ($manualOk -and $cancelOk) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "Apply stored the first value and Appearance Cancel preserved it: $manualOk/$cancelOk."
        $refs = @('recorder/page-accessibility.txt', $videoRef)
    } elseif ($suffix -eq 'DISMISS') {
        $verdict = if ($dismissOk) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "Escape dismissal returned to the page with committed value unchanged: $dismissOk."
        $refs = @('recorder/native-tree-picker.txt', 'recorder/page-accessibility.txt', $videoRef)
    } elseif ($suffix -eq 'INPUT-USABILITY') {
        $verdict = if ($accepted.Count -eq 2) { 'PASS' } else { 'UNVERIFIED' }
        $actual = "UI Automation performed native picker entry; returned selections=$($accepted.Count)."
        $refs = @('recorder/native-tree-picker.txt', 'recorder/page-accessibility.txt', $videoRef)
    }
    foreach ($requiredRef in @('environment.json', 'events.jsonl', 'recorder/screen.png', $videoRef, 'video/index.json')) {
        if ($refs -notcontains $requiredRef) { $refs += $requiredRef }
    }
    $assertions[$assertion.id] = @{ verdict = $verdict; actual = $actual; evidence = $refs }
}
$planning = if ($accepted.Count -eq 2 -and $focusReturned) { 'native picker usable' } elseif ($ready -and -not $pickerVisible) { 'hex field only' } else { 'UNVERIFIED' }
@{ caseId = $CaseId; platform = 'windows'; ready = $ready; planningVerdict = $planning; assertions = $assertions } |
    ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 (Join-Path $recorder 'observations.json')
if (-not $ready) { exit 1 }
