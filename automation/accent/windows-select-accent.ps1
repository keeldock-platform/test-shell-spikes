param(
    [Parameter(Mandatory = $true)][string]$AccentName,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName WindowsBase
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$frameworkReferences = @(Get-ChildItem -LiteralPath (Join-Path $PSHOME 'ref') -Filter '*.dll' | Select-Object -ExpandProperty FullName)
Add-Type -Path (Join-Path $PSScriptRoot '../windows/ScopedUia.cs') -ReferencedAssemblies (@(
    [System.Windows.Automation.AutomationElement].Assembly.Location,
    [System.Windows.Automation.ControlType].Assembly.Location,
    [System.Windows.Rect].Assembly.Location
) + $frameworkReferences)
Start-Process 'ms-settings:colors'
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$target = $null
$observed = @()
while ((Get-Date) -lt $deadline -and $null -eq $target) {
    $settings = Get-Process -Name SystemSettings -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($settings) {
        try {
            Write-Output ("Settings window probe: " + (@{ pid=$settings.Id; handle=$settings.MainWindowHandle.ToInt64(); title=$settings.MainWindowTitle; session=$settings.SessionId } | ConvertTo-Json -Compress))
            $window = [ScopedUia]::WindowForPid($settings.Id)
            if ($window) {
                $nodes = [ScopedUia]::Walk($window, 18, 1500)
                $observed = @($nodes | ForEach-Object {
                    $info = [ScopedUia]::Info($_)
                    [pscustomobject]@{ name=$info.Name; role=$info.ControlType.ProgrammaticName; id=$info.AutomationId; class=$info.ClassName; help=([ScopedUia]::Help($_)) }
                    if ($info.Name -eq $AccentName -and $info.ControlType -in @(
                        [System.Windows.Automation.ControlType]::RadioButton,
                        [System.Windows.Automation.ControlType]::Button)) { $script:target = $_ }
                })
            }
        } catch { Write-Output "Accent UIA probe: $($_.Exception.Message)" }
    }
    if ($null -eq $target) { Start-Sleep -Milliseconds 250 }
}
$observed | ConvertTo-Json -Depth 4 | Write-Output
if ($null -eq $target) {
    throw "Accent control '$AccentName' was not found in the scoped Settings tree; see the observed names above."
}

$pattern = $null
if (-not $target.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) {
    if (-not $target.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
        throw "Accent radio button '$AccentName' exposes no selection or invoke pattern."
    }
}
if ($pattern -is [System.Windows.Automation.SelectionItemPattern]) {
    $pattern.Select()
} else {
    $pattern.Invoke()
}
Start-Sleep -Seconds 1
Write-Output "selected:$AccentName"
