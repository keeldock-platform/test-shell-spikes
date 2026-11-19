param(
    [Parameter(Mandatory = $true)][string]$AccentName,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Start-Process 'ms-settings:colors'

$root = [System.Windows.Automation.AutomationElement]::RootElement
$nameCondition = [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    $AccentName
)
$radioCondition = [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::RadioButton
)
$condition = [System.Windows.Automation.AndCondition]::new(
    [System.Windows.Automation.Condition[]]@($nameCondition, $radioCondition)
)
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$target = $null
while ((Get-Date) -lt $deadline -and $null -eq $target) {
    $target = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
    if ($null -eq $target) { Start-Sleep -Milliseconds 250 }
}
if ($null -eq $target) {
    throw "Accent radio button '$AccentName' was not found in Settings UI Automation."
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
