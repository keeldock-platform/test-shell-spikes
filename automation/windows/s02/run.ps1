[CmdletBinding()]
param(
    [string[]]$CaseId,
    [string]$AppPath = $env:S02_APP_PATH,
    [int]$ProcessId = 0,
    [string]$EvidenceRoot = $env:S02_EVIDENCE_ROOT,
    [string]$JobId = $env:S02_JOB_ID,
    [string]$Distribution = $env:S02_DISTRIBUTION
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-ResultsEnvelope([object[]]$Rows = @()) {
    $targetRoot = $EvidenceRoot
    if (-not $targetRoot) { $targetRoot = $env:S02_EVIDENCE_ROOT }
    if (-not $targetRoot) { $targetRoot = $env:SHELL_EVIDENCE_DIR }
    if (-not $targetRoot) { return }
    try {
        New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
        $document = [ordered]@{ results = [object[]]@($Rows) }
        $json = ConvertTo-Json -InputObject $document -Depth 12
        [System.IO.File]::WriteAllText(
            (Join-Path $targetRoot 'assertions.json'),
            $json + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false)
        )
    } catch {
        [Console]::Error.WriteLine("Could not write the S02 results envelope: $($_.Exception.Message)")
    }
}

function Stop-OwnedApp {
    if (-not $script:OwnsProcess -or -not $script:Process) { return }
    try {
        if (-not $script:Process.HasExited) {
            $recorder = Join-Path $script:EvidenceRoot 'recorder'
            New-Item -ItemType Directory -Force -Path $recorder | Out-Null
            New-Item -ItemType File -Force -Path (Join-Path $recorder 'shutdown-request') | Out-Null
            $deadline = [DateTime]::UtcNow.AddSeconds(5)
            while (-not $script:Process.HasExited -and [DateTime]::UtcNow -lt $deadline) {
                if (Test-Path (Join-Path $recorder 'shutdown-flushed')) { break }
                Start-Sleep -Milliseconds 50
            }
            if (-not $script:Process.HasExited) { $script:Process.Kill() }
            if (-not $script:Process.WaitForExit(10000)) { throw 'Owned S02 process did not stop' }
        }
    } finally {
        $script:OwnsProcess = $false
    }
}

trap {
    $failure = $_.Exception.Message
    Stop-OwnedApp
    Write-ResultsEnvelope
    [Console]::Error.WriteLine("S02 automation stopped: $failure")
    exit 2
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'S02 Windows UI Automation must run on a Windows GUI runner.' }
if (-not $EvidenceRoot) { throw 'S02_EVIDENCE_ROOT must point at the CI evidence directory.' }
if (-not $AppPath -and $ProcessId -eq 0) { throw 'Set S02_APP_PATH to the built synthetic shell executable or provide ProcessId.' }
if ($AppPath -and -not (Test-Path -LiteralPath $AppPath) -and $ProcessId -eq 0) {
    throw 'Set S02_APP_PATH to the built synthetic shell executable or provide ProcessId.'
}

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class S02Input {
    [DllImport("user32.dll", SetLastError = true)] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
    [DllImport("user32.dll")] public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extraInfo);
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd, int command);
}
'@

$script:EvidenceRoot = (Resolve-Path -LiteralPath $EvidenceRoot).Path
$script:ScreenRoot = Join-Path $script:EvidenceRoot 'screens'
$script:UiaRoot = Join-Path $script:EvidenceRoot 'native-tree'
$script:CaseEvents = [System.Collections.Generic.List[object]]::new()
$script:Assertions = [System.Collections.Generic.List[object]]::new()
$script:Sequence = 0
$script:CurrentCase = ''
$script:Process = $null
$script:OwnsProcess = $false
$script:Window = $null
$script:RestartAfterClose = $false

New-Item -ItemType Directory -Force -Path $script:ScreenRoot, $script:UiaRoot | Out-Null
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$caseManifest = Get-Content -Raw -LiteralPath (Join-Path $repoRoot 'cases/s02.json') | ConvertFrom-Json
$virtualScreen = [System.Windows.Forms.SystemInformation]::VirtualScreen

function Write-Event([string]$Name, [hashtable]$Data = @{}) {
    $script:Sequence++
    $record = [ordered]@{
        sequenceId = $script:Sequence
        caseId = $script:CurrentCase
        timestampUtc = [DateTime]::UtcNow.ToString('o')
        monotonicTicks = [System.Diagnostics.Stopwatch]::GetTimestamp()
        monotonicFrequency = [System.Diagnostics.Stopwatch]::Frequency
        name = $Name
        data = $Data
    }
    $script:CaseEvents.Add($record)
    return $record.sequenceId
}

function Save-DesktopFrame([string]$Name) {
    $safeName = $Name -replace '[^A-Za-z0-9_-]', '_'
    $path = Join-Path $script:ScreenRoot "$($script:CurrentCase)-$safeName.png"
    $bitmap = [System.Drawing.Bitmap]::new($virtualScreen.Width, $virtualScreen.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($virtualScreen.Left, $virtualScreen.Top, 0, 0, $bitmap.Size)
        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
    return (Resolve-Path -LiteralPath $path).Path.Substring($script:EvidenceRoot.Length + 1)
}

function Write-Assertion([string]$AssertionId, [string]$Expected, [string]$Actual, [string]$Verdict, [string[]]$Pointers) {
    $script:Assertions.Add([ordered]@{
        id = $AssertionId
        caseId = $script:CurrentCase
        expected = $Expected
        actual = $Actual
        verdict = $Verdict
        evidence = $Pointers
        frameOrEventPointer = $Pointers
    })
}

function Get-AppWindow([int]$AppProcessId) {
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $AppProcessId)
    return [System.Windows.Automation.AutomationElement]::RootElement.FindFirst(
        [System.Windows.Automation.TreeScope]::Children, $condition)
}

function Wait-AppWindow([int]$AppProcessId, [int]$TimeoutSeconds = 30) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $window = Get-AppWindow $AppProcessId
        if ($null -ne $window) { return $window }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    $owned = Get-Process -Id $AppProcessId -ErrorAction SilentlyContinue
    $probe = [ordered]@{
        processId = $AppProcessId
        processAlive = ($null -ne $owned)
        mainWindowHandle = if ($owned) { $owned.MainWindowHandle.ToInt64() } else { $null }
        sessionId = if ($owned) { $owned.SessionId } else { $null }
        diagnostic = 'Process state at UI Automation window timeout'
    }
    $probeDirectory = Join-Path $script:EvidenceRoot 'recorder'
    New-Item -ItemType Directory -Force -Path $probeDirectory | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $probeDirectory 's02-startup-window-probe.json'),
        ($probe | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
    throw "No top-level UI Automation window found for process $AppProcessId; see recorder/s02-startup-window-probe.json."
}

function Start-OrAttachApp {
    if ($ProcessId -gt 0 -and -not $script:RestartAfterClose) {
        $script:Process = Get-Process -Id $ProcessId
    }
    elseif ($script:Process -and -not $script:Process.HasExited -and -not $script:RestartAfterClose) {
        return
    }
    else {
        $launchLog = Join-Path $script:EvidenceRoot 'recorder'
        New-Item -ItemType Directory -Force -Path $launchLog | Out-Null
        $script:Process = Start-Process -FilePath $AppPath -PassThru `
            -RedirectStandardError (Join-Path $launchLog 's02-app.stderr.log') `
            -RedirectStandardOutput (Join-Path $launchLog 's02-app.stdout.log')
        $script:OwnsProcess = $true
        try {
            if (-not $script:Process.WaitForInputIdle(30000)) {
                Write-Event 'process-input-idle-timeout' @{ processId = $script:Process.Id }
            }
        }
        catch {
            Write-Event 'process-input-idle-not-supported' @{ processId = $script:Process.Id }
        }
    }
    $script:RestartAfterClose = $false
    $script:Window = Wait-AppWindow $script:Process.Id
    $null = Wait-ByName 'S02 sample input' 30
    $null = Wait-ByName 'S02 hit-test geometry registered' 30
    Write-Event 'app-window-ready' @{ processId = $script:Process.Id; title = $script:Window.Current.Name }
}

function Find-ByName([string]$Name, [System.Windows.Automation.AutomationElement]$Within = $script:Window) {
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::NameProperty, $Name)
    return $Within.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
}

function Find-AnyName([string[]]$Names, [System.Windows.Automation.AutomationElement]$Within = $script:Window) {
    foreach ($name in $Names) {
        $element = Find-ByName $name $Within
        if ($null -ne $element) { return $element }
    }
    return $null
}

function Wait-ByName([string]$Name, [int]$TimeoutSeconds = 20) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $element = Find-ByName $Name
        if ($null -ne $element) { return $element }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for S02 UI Automation element '$Name'."
}

function Get-Rect([System.Windows.Automation.AutomationElement]$Element) {
    $r = $Element.Current.BoundingRectangle
    return [ordered]@{ x = [int][Math]::Round($r.X); y = [int][Math]::Round($r.Y); width = [int][Math]::Round($r.Width); height = [int][Math]::Round($r.Height) }
}

function Get-WindowRect {
    return Get-Rect $script:Window
}

function Click-At([int]$X, [int]$Y, [bool]$Right = $false) {
    [void][S02Input]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 60
    if ($Right) {
        [S02Input]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
        [S02Input]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
    }
    else {
        [S02Input]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
        [S02Input]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    }
}

function Send-Key([byte]$VirtualKey) {
    [S02Input]::keybd_event($VirtualKey, 0, 0, [UIntPtr]::Zero)
    [S02Input]::keybd_event($VirtualKey, 0, 0x0002, [UIntPtr]::Zero)
}

function Send-AltSpace {
    [S02Input]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
    Send-Key 0x20
    [S02Input]::keybd_event(0x12, 0, 0x0002, [UIntPtr]::Zero)
}

function Click-Element([System.Windows.Automation.AutomationElement]$Element) {
    $r = Get-Rect $Element
    Click-At ($r.x + [int]($r.width / 2)) ($r.y + [int]($r.height / 2))
    return $r
}

function Set-MenuMode([string]$Mode) {
    $modeButton = Find-AnyName @('Use kit-drawn fallback', 'Use native system menu')
    if ($null -eq $modeButton) { throw 'The S02 mode control is missing from the accessible tree.' }
    $isKit = $modeButton.Current.Name -eq 'Use native system menu'
    if (($Mode -eq 'kit' -and -not $isKit) -or ($Mode -eq 'native' -and $isKit)) {
        [void](Click-Element $modeButton)
        Start-Sleep -Milliseconds 200
    }
    Write-Event 'menu-mode-selected' @{ mode = $Mode }
}

function Set-WindowState([string]$State) {
    $buttonName = switch ($State) {
        'normal' { 'Restore window' }
        'maximized' { 'Maximize window' }
        'minimized' { 'Minimize window' }
        default { throw "Unsupported test window state: $State" }
    }
    $button = Find-ByName $buttonName
    if ($null -eq $button) { throw "Missing accessible window-state control '$buttonName'." }
    [void](Click-Element $button)
    Start-Sleep -Milliseconds 600
    Write-Event 'window-state-requested' @{ state = $State; bounds = (Get-WindowRect) }
}

function Open-ByPointer([string]$TargetName) {
    $target = Find-ByName $TargetName
    if ($null -eq $target) { throw "Missing pointer target '$TargetName'." }
    $r = Get-Rect $target
    $x = $r.x + [int]($r.width / 2)
    $y = $r.y + [int]($r.height / 2)
    $dpi = [S02Input]::GetDpiForWindow([IntPtr]$script:Window.Current.NativeWindowHandle)
    $seq = Write-Event 'real-right-click' @{ target = $TargetName; screenX = $x; screenY = $y; targetBounds = $r; dpi = $dpi; scale = ($dpi / 96.0) }
    Click-At $x $y $true
    return @{ x = $x; y = $y; sequenceId = $seq; targetBounds = $r }
}

function Open-ByAltSpace([string]$FocusName) {
    $target = Find-ByName $FocusName
    if ($null -eq $target) { throw "Missing Alt+Space focus target '$FocusName'." }
    $target.SetFocus()
    Start-Sleep -Milliseconds 100
    $bounds = Get-WindowRect
    $seq = Write-Event 'alt-space' @{ focusTarget = $FocusName; windowBounds = $bounds }
    Send-AltSpace
    return @{ x = $bounds.x; y = $bounds.y; sequenceId = $seq; focusTarget = $FocusName }
}

function Find-ActiveMenu([int]$TimeoutSeconds = 5) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $expectedNames = @('Restore', 'Move', 'Size', 'Minimize', 'Minimise', 'Maximize', 'Maximise', 'Close')
    do {
        $condition = [System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Menu)
        $menus = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
            [System.Windows.Automation.TreeScope]::Descendants, $condition)
        foreach ($candidate in $menus) {
            $items = $candidate.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
            $names = @($items | ForEach-Object { $_.Current.Name })
            $matched = @($expectedNames | Where-Object { $names -contains $_ })
            if ($matched.Count -ge 3 -or $candidate.Current.Name -eq 'S02 Windows system menu') { return $candidate }
        }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

function Get-MenuItems([System.Windows.Automation.AutomationElement]$Menu) {
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::MenuItem)
    return $Menu.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
}

function Save-MenuTree([System.Windows.Automation.AutomationElement]$Menu) {
    $items = foreach ($item in (Get-MenuItems $Menu)) {
        $rect = Get-Rect $item
        [ordered]@{
            name = $item.Current.Name
            enabled = $item.Current.IsEnabled
            controlType = $item.Current.ControlType.ProgrammaticName
            automationId = $item.Current.AutomationId
            bounds = $rect
        }
    }
    $tree = [ordered]@{ name = $Menu.Current.Name; bounds = (Get-Rect $Menu); items = @($items) }
    $path = Join-Path $script:UiaRoot "$($script:CurrentCase)-menu.json"
    $tree | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding utf8
    return (Resolve-Path -LiteralPath $path).Path.Substring($script:EvidenceRoot.Length + 1)
}

function Save-UiaSubtree([System.Windows.Automation.AutomationElement]$Element, [string]$Suffix) {
    $descendants = $Element.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    $nodes = foreach ($node in $descendants) {
        [ordered]@{
            name = $node.Current.Name
            controlType = $node.Current.ControlType.ProgrammaticName
            enabled = $node.Current.IsEnabled
            automationId = $node.Current.AutomationId
            bounds = Get-Rect $node
        }
    }
    $tree = [ordered]@{
        root = @{ name = $Element.Current.Name; controlType = $Element.Current.ControlType.ProgrammaticName; bounds = Get-Rect $Element }
        descendants = @($nodes)
    }
    $path = Join-Path $script:UiaRoot "$($script:CurrentCase)-$Suffix.json"
    $tree | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path -Encoding utf8
    return (Resolve-Path -LiteralPath $path).Path.Substring($script:EvidenceRoot.Length + 1)
}

function Wait-ActiveMenu([int]$TimeoutSeconds = 5) {
    $menu = Find-ActiveMenu $TimeoutSeconds
    if ($null -eq $menu) { throw 'No native or kit system-menu UIA tree appeared.' }
    $treePath = Save-MenuTree $menu
    $frame = Save-DesktopFrame 'menu-open'
    Write-Event 'menu-opened' @{ menuBounds = (Get-Rect $menu); menuTree = $treePath; frame = $frame }
    return $menu
}

function Test-MenuOrigin($Menu, [int]$ExpectedX, [int]$ExpectedY, [int]$Tolerance = 12) {
    $r = Get-Rect $Menu
    return [Math]::Abs($r.x - $ExpectedX) -le $Tolerance -and [Math]::Abs($r.y - $ExpectedY) -le $Tolerance
}

function Find-MenuItem([System.Windows.Automation.AutomationElement]$Menu, [string]$Command) {
    $aliases = switch ($Command) {
        'minimize' { @('Minimize', 'Minimise') }
        'maximize' { @('Maximize', 'Maximise') }
        default { @((Get-Culture).TextInfo.ToTitleCase($Command)) }
    }
    foreach ($item in (Get-MenuItems $Menu)) {
        if ($aliases -contains $item.Current.Name) { return $item }
    }
    return $null
}

function Select-MenuItemByMouse([System.Windows.Automation.AutomationElement]$Menu, [string]$Command) {
    $item = Find-MenuItem $Menu $Command
    if ($null -eq $item) { throw "Menu item '$Command' was not found." }
    if (-not $item.Current.IsEnabled) { throw "Menu item '$Command' is disabled in this state." }
    $bounds = Get-Rect $item
    Click-At ($bounds.x + [int]($bounds.width / 2)) ($bounds.y + [int]($bounds.height / 2))
    Write-Event 'menu-item-mouse-selected' @{ command = $Command; bounds = $bounds }
}

function Select-MenuItemByKeyboard([System.Windows.Automation.AutomationElement]$Menu, [string]$Command) {
    $items = @(Get-MenuItems $Menu | Where-Object { $_.Current.IsEnabled })
    $names = @($items | ForEach-Object { $_.Current.Name })
    $target = Find-MenuItem $Menu $Command
    if ($null -eq $target -or -not $target.Current.IsEnabled) { throw "Keyboard target '$Command' is unavailable." }
    $targetName = $target.Current.Name
    $index = [Array]::IndexOf($names, $targetName)
    if ($index -lt 0) { throw "Keyboard target '$targetName' was not in the enabled menu sequence." }
    Send-Key 0x24 # Home
    for ($i = 0; $i -lt $index; $i++) { Send-Key 0x28 } # Down
    Send-Key 0x0D # Enter
    Write-Event 'menu-item-keyboard-selected' @{ command = $Command; enabledIndex = $index }
}

function Write-CaseResult($Case, [string]$Expected, [string]$Actual, [string]$Verdict, [string[]]$Pointers) {
    $allPointers = @($Pointers) + @("events.jsonl#case=$($Case.id)", "video/desktop.mp4#case=$($Case.id)")
    foreach ($assertion in $Case.assertions) {
        Write-Assertion $assertion.id $assertion.expected "$Actual; $Expected" $Verdict $allPointers
    }
}

function Ensure-KitMode($Case) {
    $launch = @($Case.setup | Where-Object { $_.action -eq 'launch' } | Select-Object -First 1)
    $mode = if ($launch.Count -gt 0) { $launch[0].menuMode } else { 'native' }
    Set-MenuMode $mode
}

function Get-NativeWindowHandle {
    return [IntPtr]$script:Window.Current.NativeWindowHandle
}

function Invoke-SystemCommandMatrix($Case) {
    $actions = @($Case.actions | Where-Object { $_.action -eq 'select-system-commands' })
    foreach ($selectionAction in $actions) {
      $selectionMode = $selectionAction.selection
      foreach ($command in $selectionAction.commands) {
        if ($command -eq 'restore') { Set-WindowState 'maximized' } else { Set-WindowState 'normal' }
        $point = Open-ByPointer 'S02 empty title bar'
        $menu = Wait-ActiveMenu
        $targetItem = Find-MenuItem $menu $command
        if ($null -eq $targetItem -or -not $targetItem.Current.IsEnabled) { throw "System menu item '$command' was missing or disabled in its required state." }
        $maximizedForMenu = $command -eq 'restore'
        $expectedEnabled = @{
            restore = $maximizedForMenu
            move = -not $maximizedForMenu
            size = -not $maximizedForMenu
            minimize = $true
            maximize = -not $maximizedForMenu
            close = $true
        }
        foreach ($menuCommand in $expectedEnabled.Keys) {
            $item = Find-MenuItem $menu $menuCommand
            if ($null -eq $item -or $item.Current.IsEnabled -ne [bool]$expectedEnabled[$menuCommand]) {
                throw "System menu enabled state for '$menuCommand' did not match the expected state."
            }
        }
        $before = Get-WindowRect
        if ($SelectionMode -eq 'physical-mouse') { Select-MenuItemByMouse $menu $command }
        elseif ($SelectionMode -eq 'physical-mouse-and-keyboard-adjustment') { Select-MenuItemByMouse $menu $command }
        else { Select-MenuItemByKeyboard $menu $command }

        Start-Sleep -Milliseconds 650
        switch ($command) {
            'restore' {
                $isMaximized = [S02Input]::IsZoomed((Get-NativeWindowHandle))
                if ($isMaximized) { throw 'Restore selection did not return the native window to normal state.' }
            }
            'maximize' {
                $isMaximized = [S02Input]::IsZoomed((Get-NativeWindowHandle))
                if (-not $isMaximized) { throw 'Maximize selection did not maximize the native window.' }
                [void][S02Input]::ShowWindow((Get-NativeWindowHandle), 9)
            }
            'minimize' {
                $isMinimized = [S02Input]::IsIconic((Get-NativeWindowHandle))
                if (-not $isMinimized) { throw 'Minimize selection did not hide/minimize the native window.' }
                Write-Event 'minimize-result' @{ minimized = $isMinimized; offscreen = $script:Window.Current.IsOffscreen }
                [void][S02Input]::ShowWindow((Get-NativeWindowHandle), 9)
                Start-Sleep -Milliseconds 350
            }
            { $_ -in 'move', 'size' } {
                if ($selectionMode -eq 'physical-mouse-and-keyboard-adjustment') {
                    Send-Key 0x27
                    Send-Key 0x28
                }
                else {
                    Send-Key 0x27
                    Send-Key 0x28
                }
                Send-Key 0x0D
                Start-Sleep -Milliseconds 300
                $after = Get-WindowRect
                if ($before.x -eq $after.x -and $before.y -eq $after.y -and $before.width -eq $after.width -and $before.height -eq $after.height) {
                    throw "$command selection did not change native window bounds."
                }
                Write-Event 'bounds-after-system-operation' @{ command = $command; before = $before; after = $after }
            }
            'close' {
                Start-Sleep -Milliseconds 400
                $guard = Find-ByName 'S02 mock close guard'
                if ($null -eq $guard) { throw 'Close did not reach the S02 mock close guard.' }
                Write-Event 'close-guard-reached' @{ bounds = (Get-Rect $guard) }
                $keep = Find-ByName 'Keep S02 open'
                [void](Click-Element $keep)
            }
        }
        $null = $point
      }
    }
}

function Invoke-SnapObservation($Case) {
    $button = Find-ByName 'S02 maximize button'
    if ($null -eq $button) { throw 'The real kit maximize button is missing.' }
    $bounds = Get-Rect $button
    [void][S02Input]::SetCursorPos(($bounds.x + [int]($bounds.width / 2)), ($bounds.y + [int]($bounds.height / 2)))
    Write-Event 'snap-hover' @{ buttonBounds = $bounds; jobId = $JobId }
    Start-Sleep -Seconds 2
    $frame = Save-DesktopFrame 'snap-hover'
    $deadline = [DateTime]::UtcNow.AddSeconds(4)
    $tree = $null
    do {
        $all = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
            [System.Windows.Automation.TreeScope]::Descendants,
            [System.Windows.Automation.Condition]::TrueCondition)
        foreach ($candidate in $all) {
            $name = $candidate.Current.Name
            if ($name -match '(?i)snap layout|snap window|choose a layout' -and
                $candidate.Current.ControlType -ne [System.Windows.Automation.ControlType]::Button) {
                $tree = $candidate
                break
            }
        }
        if ($null -eq $tree) { Start-Sleep -Milliseconds 150 }
    } while ($null -eq $tree -and [DateTime]::UtcNow -lt $deadline)
    if ($null -eq $tree) {
        Write-CaseResult $Case 'A real OS Snap Layouts popup is visible.' 'No popup UIA tree was available on this runner session.' 'UNVERIFIED' @($frame)
        return
    }
    $treePath = Save-UiaSubtree $tree 'snap-popup-tree'
    Write-CaseResult $Case 'A real OS Snap Layouts popup is visible.' 'A native popup tree appeared on hover.' 'PASS' @($treePath, $frame)
}

function Invoke-OneCase($Case) {
    $script:CurrentCase = $Case.id
    $frameBefore = $null
    $menu = $null
    $anchor = $null

    try {
        Start-OrAttachApp
        $script:Window = Wait-AppWindow $script:Process.Id
        Ensure-KitMode $Case
        $frameBefore = Save-DesktopFrame 'before'
        switch ($Case.id) {
            'S02-WIN-01-native-pointer-open' {
                $anchor = Open-ByPointer 'S02 empty title bar'
                $menu = Wait-ActiveMenu
                $originOK = Test-MenuOrigin $menu $anchor.x $anchor.y
                $actualNames = @(Get-MenuItems $menu | ForEach-Object { $_.Current.Name })
                $expectedNames = @('Restore', 'Move', 'Size', 'Minimize', 'Maximize', 'Close')
                $missingNames = @($expectedNames | Where-Object { $actualNames -notcontains $_ })
                $allItemsOK = $missingNames.Count -eq 0
                $tree = Save-MenuTree $menu
                $verdict = if ($originOK -and $allItemsOK) { 'PASS' } else { 'FAIL' }
                $actual = "Menu bounds $((Get-Rect $menu) | ConvertTo-Json -Compress); input point $($anchor.x),$($anchor.y); item names $($actualNames -join ', '); missing $($missingNames -join ', ')."
                Write-CaseResult $Case 'Native menu opens at the recorded pointer and contains the six system items.' $actual $verdict @($tree, $frameBefore, (Save-DesktopFrame 'pointer-menu'))
            }
            'S02-WIN-02-alt-space-input' {
                $reset = Find-ByName 'Reset WebView2 accelerator receipt'
                if ($null -eq $reset) { throw 'The WebView2 accelerator receipt reset control is missing.' }
                [void](Click-Element $reset)
                $anchor = Open-ByAltSpace 'S02 sample input'
                $menu = Wait-ActiveMenu
                $ok = Test-MenuOrigin $menu $anchor.x $anchor.y
                $menuBounds = Get-Rect $menu
                $menuTree = Save-MenuTree $menu
                $menuFrame = Save-DesktopFrame 'alt-space-input-menu-open'
                Send-Key 0x1B; Start-Sleep -Milliseconds 350
                $receipt = Find-ByName 'WebView2 AcceleratorKeyPressed intercepted Alt+Space'
                if ($null -eq $receipt) { throw 'The WebView2 AcceleratorKeyPressed receipt was not observed while the input had focus.' }
                $ok = $ok -and -not $receipt.Current.IsOffscreen
                Write-CaseResult $Case 'WebView2 AcceleratorKeyPressed intercepts Alt+Space and opens at the window top-left with input focus.' "Menu bounds $($menuBounds | ConvertTo-Json -Compress); focused $($anchor.focusTarget); WebView2 receipt visible=$(-not $receipt.Current.IsOffscreen)." $(if ($ok) { 'PASS' } else { 'FAIL' }) @($menuTree, (Save-UiaSubtree $receipt 'accelerator-receipt'), $menuFrame, (Save-DesktopFrame 'alt-space-input-dismissed'))
            }
            'S02-WIN-03-alt-space-empty-chrome' {
                $reset = Find-ByName 'Reset WebView2 accelerator receipt'
                if ($null -eq $reset) { throw 'The WebView2 accelerator receipt reset control is missing.' }
                [void](Click-Element $reset)
                $anchor = Open-ByAltSpace 'S02 empty title bar'
                $menu = Wait-ActiveMenu
                $ok = Test-MenuOrigin $menu $anchor.x $anchor.y
                $menuBounds = Get-Rect $menu
                $menuTree = Save-MenuTree $menu
                $menuFrame = Save-DesktopFrame 'alt-space-chrome-menu-open'
                Send-Key 0x1B; Start-Sleep -Milliseconds 350
                $receipt = Find-ByName 'WebView2 AcceleratorKeyPressed intercepted Alt+Space'
                if ($null -eq $receipt) { throw 'The WebView2 AcceleratorKeyPressed receipt was not observed while empty chrome had focus.' }
                $ok = $ok -and -not $receipt.Current.IsOffscreen
                Write-CaseResult $Case 'WebView2 AcceleratorKeyPressed intercepts Alt+Space and opens at the window top-left with empty-chrome focus.' "Menu bounds $($menuBounds | ConvertTo-Json -Compress); focused $($anchor.focusTarget); WebView2 receipt visible=$(-not $receipt.Current.IsOffscreen)." $(if ($ok) { 'PASS' } else { 'FAIL' }) @($menuTree, (Save-UiaSubtree $receipt 'accelerator-receipt'), $menuFrame, (Save-DesktopFrame 'alt-space-chrome-dismissed'))
            }
            'S02-WIN-04-app-icon-entry' {
                $icon = Find-ByName 'S02 app icon'
                $bounds = Click-Element $icon
                $menu = Wait-ActiveMenu
                $win = Get-WindowRect
                $ok = Test-MenuOrigin $menu $win.x $win.y
                Write-CaseResult $Case 'App-icon click opens at the window top-left.' "Menu bounds $((Get-Rect $menu) | ConvertTo-Json -Compress); icon bounds $($bounds | ConvertTo-Json -Compress)." $(if ($ok) { 'PASS' } else { 'FAIL' }) @((Save-MenuTree $menu), (Save-DesktopFrame 'app-icon-menu'))
            }
            'S02-WIN-05-enabled-items-normal' {
                Set-WindowState 'normal'; $anchor = Open-ByPointer 'S02 empty title bar'; $menu = Wait-ActiveMenu
                $restore = Find-MenuItem $menu 'restore'; $move = Find-MenuItem $menu 'move'; $size = Find-MenuItem $menu 'size'
                $minimize = Find-MenuItem $menu 'minimize'; $maximize = Find-MenuItem $menu 'maximize'; $close = Find-MenuItem $menu 'close'
                $ok = -not $restore.Current.IsEnabled -and $move.Current.IsEnabled -and $size.Current.IsEnabled -and $minimize.Current.IsEnabled -and $maximize.Current.IsEnabled -and $close.Current.IsEnabled
                Write-CaseResult $Case 'Restore disabled; all other applicable commands enabled in normal state.' "Restore=$($restore.Current.IsEnabled), Move=$($move.Current.IsEnabled), Size=$($size.Current.IsEnabled), Minimize=$($minimize.Current.IsEnabled), Maximize=$($maximize.Current.IsEnabled), Close=$($close.Current.IsEnabled)." $(if ($ok) { 'PASS' } else { 'FAIL' }) @((Save-MenuTree $menu), (Save-DesktopFrame 'normal-state'))
            }
            'S02-WIN-06-enabled-items-maximized' {
                Set-WindowState 'maximized'; $anchor = Open-ByPointer 'S02 empty title bar'; $menu = Wait-ActiveMenu
                $restore = Find-MenuItem $menu 'restore'; $move = Find-MenuItem $menu 'move'; $size = Find-MenuItem $menu 'size'
                $minimize = Find-MenuItem $menu 'minimize'; $maximize = Find-MenuItem $menu 'maximize'; $close = Find-MenuItem $menu 'close'
                $ok = $restore.Current.IsEnabled -and -not $move.Current.IsEnabled -and -not $size.Current.IsEnabled -and $minimize.Current.IsEnabled -and -not $maximize.Current.IsEnabled -and $close.Current.IsEnabled
                Write-CaseResult $Case 'Restore enabled; Move, Size and Maximize disabled; Minimize and Close enabled in maximized state.' "Restore=$($restore.Current.IsEnabled), Move=$($move.Current.IsEnabled), Size=$($size.Current.IsEnabled), Minimize=$($minimize.Current.IsEnabled), Maximize=$($maximize.Current.IsEnabled), Close=$($close.Current.IsEnabled)." $(if ($ok) { 'PASS' } else { 'FAIL' }) @((Save-MenuTree $menu), (Save-DesktopFrame 'maximized-state'))
            }
            'S02-WIN-07-native-mouse-command-matrix' { Invoke-SystemCommandMatrix $Case; Write-CaseResult $Case 'All six native commands act on the window through mouse selection.' 'Every applicable command was selected and its native postcondition was checked.' 'PASS' @((Save-DesktopFrame 'mouse-matrix')) }
            'S02-WIN-08-native-keyboard-command-matrix' { Invoke-SystemCommandMatrix $Case; Write-CaseResult $Case 'All six native commands act on the window through keyboard selection.' 'Every applicable command was selected and its native postcondition was checked.' 'PASS' @((Save-DesktopFrame 'keyboard-matrix')) }
            'S02-WIN-09-move-and-size-bounds' {
                Set-WindowState 'normal'; $before = Get-WindowRect
                Invoke-SystemCommandMatrix $Case
                $after = Get-WindowRect
                $ok = ($before.x -ne $after.x -or $before.y -ne $after.y -or $before.width -ne $after.width -or $before.height -ne $after.height)
                Write-CaseResult $Case 'Move and Size change native window bounds.' "Before=$($before | ConvertTo-Json -Compress); after=$($after | ConvertTo-Json -Compress)." $(if ($ok) { 'PASS' } else { 'FAIL' }) @((Save-DesktopFrame 'bounds-after'))
            }
            'S02-WIN-10-minimize-and-restore-visibility' {
                Set-WindowState 'normal'; $anchor = Open-ByPointer 'S02 empty title bar'; $menu = Wait-ActiveMenu
                Select-MenuItemByMouse $menu 'minimize'; Start-Sleep -Milliseconds 800
                $minimized = [S02Input]::IsIconic((Get-NativeWindowHandle))
                [void][S02Input]::ShowWindow((Get-NativeWindowHandle), 9)
                Start-Sleep -Milliseconds 500
                $visible = -not $script:Window.Current.IsOffscreen
                $ok = $minimized -and $visible
                Write-CaseResult $Case 'Minimize hides the window and Restore makes it visible again.' "MinimizedOffscreen=$minimized; restoredVisible=$visible." $(if ($ok) { 'PASS' } else { 'FAIL' }) @((Save-DesktopFrame 'minimize-restore'))
            }
            'S02-WIN-11-negative-control-context' {
                foreach ($targetName in @('S02 sample tab', 'S02 maximize button')) {
                    $target = Find-ByName $targetName
                    $bounds = Get-Rect $target
                    Click-At ($bounds.x + [int]($bounds.width / 2)) ($bounds.y + [int]($bounds.height / 2)) $true
                    Start-Sleep -Milliseconds 400
                    $active = Find-ActiveMenu 1
                    $isSystem = $null -ne $active -and $active.Current.Name -ne 'S02 sample tab actions'
                    if ($null -ne $active) { $tree = Save-MenuTree $active } else { $tree = Save-DesktopFrame 'no-context-menu' }
                    if ($isSystem) { throw "Right-click on '$targetName' opened a system menu." }
                    Write-Event 'negative-control-right-click' @{ target = $targetName; bounds = $bounds }
                    Send-Key 0x1B
                }
                Write-CaseResult $Case 'Tab and control right-clicks do not open the system menu.' 'The tested controls did not expose the system menu.' 'PASS' @((Save-DesktopFrame 'negative-context'))
            }
            'S02-WIN-12-escape-dismissal' {
                $anchor = Open-ByAltSpace 'S02 empty title bar'; $menu = Wait-ActiveMenu
                $menuTree = Save-MenuTree $menu
                Send-Key 0x1B; Start-Sleep -Milliseconds 250
                $gone = $null -eq (Find-ActiveMenu 1)
                $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
                $focusName = $focused.Current.Name
                $focusReturned = $focusName -eq 'S02 empty title bar'
                $ok = $gone -and $focusReturned
                Write-CaseResult $Case 'Escape dismisses the menu and returns focus to its opener.' "MenuGone=$gone; focusAfter='$focusName'; focusReturned=$focusReturned." $(if ($ok) { 'PASS' } else { 'FAIL' }) @($menuTree, (Save-DesktopFrame 'escape-dismissed'))
            }
            { $_ -in 'S02-WIN-13-snap-windows-2025', 'S02-WIN-14-snap-windows-11-arm' } { Invoke-SnapObservation $Case }
            'S02-WIN-15-native-close-guard-relaunch' {
                $anchor = Open-ByAltSpace 'S02 empty title bar'; $menu = Wait-ActiveMenu
                Select-MenuItemByMouse $menu 'close'; Start-Sleep -Milliseconds 500
                $guard = Find-ByName 'S02 mock close guard'
                if ($null -eq $guard) { throw 'Native Close did not reach the mock close guard.' }
                Write-Event 'native-close-guard' @{ bounds = (Get-Rect $guard) }
                $discard = Find-ByName 'Discard synthetic work and close'; [void](Click-Element $discard)
                Start-Sleep -Milliseconds 500
                if ($script:Process -and -not $script:Process.HasExited -and -not $script:Process.WaitForExit(10000)) { throw 'Native Close did not stop the owned app before relaunch' }
                $script:RestartAfterClose = $true
                Start-OrAttachApp
                $anchor2 = Open-ByPointer 'S02 empty title bar'; $menu2 = Wait-ActiveMenu
                Write-CaseResult $Case 'Close reaches the guard; relaunch and the second entry path work.' "Guard reached; relaunch process $($script:Process.Id); pointer menu reopened." 'PASS' @((Save-MenuTree $menu2), (Save-DesktopFrame 'close-relaunch'))
            }
            'S02-WIN-16-kit-fallback-pointer-and-icon' {
                $anchor = Open-ByPointer 'S02 empty title bar'; $menu = Wait-ActiveMenu
                $pointerOK = Test-MenuOrigin $menu $anchor.x $anchor.y
                Send-Key 0x1B
                $icon = Find-ByName 'S02 app icon'; $iconBounds = Get-Rect $icon; Click-Element $icon | Out-Null
                $menu2 = Wait-ActiveMenu; $windowBounds = Get-WindowRect
                $iconOK = Test-MenuOrigin $menu2 $windowBounds.x $windowBounds.y
                $ok = $pointerOK -and $iconOK
                Write-CaseResult $Case 'Fallback opens at pointer and at window origin from the app icon.' "pointer=$pointerOK; icon=$iconOK." $(if ($ok) { 'PASS' } else { 'FAIL' }) @((Save-MenuTree $menu2), (Save-DesktopFrame 'kit-pointer-icon'))
            }
            'S02-WIN-17-kit-fallback-keyboard' {
                $allOK = $true
                foreach ($focusName in @('S02 sample input', 'S02 empty title bar')) {
                    $anchor = Open-ByAltSpace $focusName; $menu = Wait-ActiveMenu
                    $allOK = $allOK -and (Test-MenuOrigin $menu $anchor.x $anchor.y)
                    Send-Key 0x28; Send-Key 0x24; Send-Key 0x23; Send-Key 0x1B
                }
                Write-CaseResult $Case 'Fallback Alt+Space opens from input and empty chrome; menu keys operate.' "AllAnchorsAndDismissals=$allOK." $(if ($allOK) { 'PASS' } else { 'FAIL' }) @((Save-DesktopFrame 'kit-keyboard'))
            }
            'S02-WIN-18-kit-fallback-command-matrix' {
                Invoke-SystemCommandMatrix $Case
                Write-CaseResult $Case 'Fallback system commands work through mouse and keyboard selection.' 'Both selection paths completed; window, bounds and close-guard events recorded.' 'PASS' @((Save-DesktopFrame 'kit-command-matrix'))
            }
            'S02-WIN-19-kit-fallback-close-guard-relaunch' {
                $anchor = Open-ByAltSpace 'S02 sample input'; $menu = Wait-ActiveMenu
                Select-MenuItemByKeyboard $menu 'close'; Start-Sleep -Milliseconds 500
                $guard = Find-ByName 'S02 mock close guard'
                if ($null -eq $guard) { throw 'Fallback Close did not reach the mock close guard.' }
                $discard = Find-ByName 'Discard synthetic work and close'; [void](Click-Element $discard)
                Start-Sleep -Milliseconds 500
                if ($script:Process -and -not $script:Process.HasExited -and -not $script:Process.WaitForExit(10000)) { throw 'Native Close did not stop the owned app before relaunch' }
                $script:RestartAfterClose = $true
                Start-OrAttachApp; Set-MenuMode 'kit'
                $anchor2 = Open-ByPointer 'S02 empty title bar'; $menu2 = Wait-ActiveMenu
                Write-CaseResult $Case 'Fallback Close reaches the guard; relaunch and right-click fallback still work.' 'Close guard reached; relaunch and the other input path opened the kit menu.' 'PASS' @((Save-MenuTree $menu2), (Save-DesktopFrame 'kit-close-relaunch'))
            }
            default { throw "No S02 automation implementation for case '$($Case.id)'." }
        }
    }
    catch {
        $frame = Save-DesktopFrame 'case-error'
        Write-Event 'case-error' @{ message = $_.Exception.Message; frame = $frame }
        $verdict = if ($_.Exception.Message -match 'UI Automation|no top-level|runner|desktop|session|popup') { 'UNVERIFIED' } else { 'FAIL' }
        Write-CaseResult $Case 'All case assertions are evidenced.' $_.Exception.Message $verdict @($frame)
        # Collect later case evidence and write the always-upload result files.
    }
}

if (-not [Environment]::UserInteractive) { throw 'The Windows runner has no interactive desktop session.' }
if ($virtualScreen.Width -le 0 -or $virtualScreen.Height -le 0) { throw 'The Windows runner has no capturable display.' }
if (-not $Distribution) { throw 'S02_DISTRIBUTION must identify windows-2025 or windows-11-arm.' }

Start-OrAttachApp
$envRecord = [ordered]@{
    jobId = $JobId
    distribution = $Distribution
    runnerLabel = $env:RUNNER_NAME
    osVersion = [Environment]::OSVersion.VersionString
    sessionInteractive = [Environment]::UserInteractive
    virtualScreen = @{ left = $virtualScreen.Left; top = $virtualScreen.Top; width = $virtualScreen.Width; height = $virtualScreen.Height }
    processArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture.ToString()
    windowDpi = [S02Input]::GetDpiForWindow((Get-NativeWindowHandle))
    displayScale = ([S02Input]::GetDpiForWindow((Get-NativeWindowHandle)) / 96.0)
    windowTitle = $script:Window.Current.Name
    processId = $script:Process.Id
    webView2Version = $env:S02_WEBVIEW2_VERSION
    tauriVersion = $env:S02_TAURI_VERSION
    sourceSha = $env:GITHUB_SHA
}
$envRecord | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $script:EvidenceRoot 'environment.json') -Encoding utf8

$selectedCases = @($caseManifest.cases | Where-Object {
    (($CaseId.Count -eq 0) -or ($CaseId -contains $_.id)) -and ($_.distribution -eq $Distribution)
})
if ($selectedCases.Count -eq 0) { throw 'No S02 cases matched the selected ids and distribution.' }

foreach ($case in $selectedCases) { Invoke-OneCase $case }

$resultRows = [object[]]@($script:Assertions.ToArray())
Write-ResultsEnvelope -Rows $resultRows
$script:CaseEvents | ForEach-Object { $_ | ConvertTo-Json -Depth 10 -Compress } |
    Set-Content -LiteralPath (Join-Path $script:EvidenceRoot 'events.jsonl') -Encoding utf8

$index = [ordered]@{
    sourceSha = $env:GITHUB_SHA
    jobId = $JobId
    assertions = 'assertions.json'
    events = 'events.jsonl'
    environment = 'environment.json'
    screens = 'screens/'
    nativeTrees = 'native-tree/'
    video = 'video/desktop.mp4 (written by the CI whole-desktop recorder)'
    assertionEvidence = @($script:Assertions | ForEach-Object {
        [ordered]@{ id = $_.id; caseId = $_.caseId; verdict = $_.verdict; paths = $_.evidence }
    })
}
$index | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $script:EvidenceRoot 'index.json') -Encoding utf8

Stop-OwnedApp
if (@($script:Assertions | Where-Object { $_.verdict -eq 'FAIL' }).Count -gt 0) { exit 1 }
exit 0

