param(
    [string]$ExePath = "$PSScriptRoot\..\bin\wireless-verification\Tobatools.exe",
    [string]$ConnectEndpoint = '127.0.0.1:5555',
    [string]$UnreachableEndpoint = '10.0.2.15:5555'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$previousScope = $env:TOBATOOLS_TEST_SETTINGS_ID
$id = [Guid]::NewGuid().ToString('N')
$env:TOBATOOLS_TEST_SETTINGS_ID = $id
$p = $null
$window = $null
function U([string]$s) { [regex]::Unescape($s) }
function Find-Id([string]$name) {
    $c = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $name)
    return $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $c)
}
function Wait-For([scriptblock]$condition, [string]$message, [int]$seconds = 20) {
    $end = [DateTime]::UtcNow.AddSeconds($seconds)
    do {
        $p.Refresh()
        if ($p.HasExited) { throw "Application exited: $($p.ExitCode)" }
        if (& $condition) { return }
        [Threading.Thread]::Sleep(100)
    } while ([DateTime]::UtcNow -lt $end)
    throw $message
}
function Require-Id([string]$name) {
    Wait-For { $null -ne (Find-Id $name) } "Missing control: $name" 5
    return Find-Id $name
}
function Invoke-Id([string]$name) {
    $element = Require-Id $name
    $pattern = $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    $pattern.Invoke()
}
function Set-Input([string]$name, [string]$value) {
    $pattern = (Require-Id $name).GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $pattern.SetValue($value)
}
function Navigate([string]$name) {
    $c = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $name)
    foreach ($element in (Require-Id 'NavView').FindAll([System.Windows.Automation.TreeScope]::Descendants, $c)) {
        $pattern = $null
        if ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) {
            $pattern.Select()
            [Threading.Thread]::Sleep(400)
            return
        }
    }
    throw "Missing navigation: $name"
}
try {
    $p = Start-Process -FilePath $ExePath -PassThru
    Wait-For { $p.MainWindowHandle -ne 0 } 'No application window.' 25
    $window = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
    Navigate (U '\u955C\u50CF\u8F85\u52A9')
    Invoke-Id 'BtnConnect'
    Set-Input 'ConnectHost' 'not an endpoint'
    Invoke-Id 'PrimaryButton'
    Wait-For { (Require-Id 'TxtResult').Current.Name.Length -gt 0 } 'Invalid address had no feedback.'
    if (-not (Require-Id 'ConnectHost').Current.IsEnabled) { throw 'Invalid address incorrectly started a request.' }
    Write-Output 'VALIDATION PASS: invalid address keeps the dialog open with feedback.'

    Set-Input 'PairHost' '127.0.0.1'
    Set-Input 'PairCode' '123456'
    Invoke-Id 'BtnPair'
    Wait-For { (Require-Id 'TxtResult').Current.Name -like ('*' + (U '\u7AEF\u53E3') + '*') } 'Pairing accepted an address without its pairing port.'
    Write-Output 'PAIRING VALIDATION PASS: pairing requires an explicit port and does not reuse port 5555.'

    Set-Input 'ConnectHost' $UnreachableEndpoint
    Invoke-Id 'PrimaryButton'
    Wait-For { -not (Require-Id 'ConnectHost').Current.IsEnabled } 'Connection did not enter busy state.' 3
    [Threading.Thread]::Sleep(300)
    if ($null -eq (Find-Id 'ConnectHost')) { throw 'Dialog closed before connection completed.' }
    if ((Require-Id 'PrimaryButton').Current.IsEnabled -or (Require-Id 'BtnPair').Current.IsEnabled) { throw 'Concurrent requests remain enabled.' }
    Write-Output 'DEFERRAL PASS: dialog remains open while waiting; duplicate actions are disabled.'
    Wait-For { (Require-Id 'ConnectHost').Current.IsEnabled } 'Connection did not finish within its timeout.' 20
    $errorText = (Require-Id 'TxtResult').Current.Name
    if ($errorText -notlike ('*' + (U '\u8FDE\u63A5\u5931\u8D25') + '*')) { throw "Expected connection failure, got: $errorText" }
    if ($UnreachableEndpoint -like '10.0.2.15:*' -and $errorText -notlike '*NAT*') { throw 'Emulator NAT diagnostic is missing.' }
    Write-Output 'FAILURE PASS: timeout stays visible in the dialog with endpoint guidance.'

    Set-Input 'ConnectHost' $ConnectEndpoint
    Invoke-Id 'PrimaryButton'
    Wait-For { $null -eq (Find-Id 'ConnectHost') } 'Successful connection did not close the dialog.' 20
    Wait-For { (Require-Id 'TxtSerial').Current.Name.Contains($ConnectEndpoint) } 'Device banner did not refresh to the connected endpoint.' 30
    Write-Output "CONNECT PASS: $ConnectEndpoint connected and the device banner refreshed."

    Invoke-Id 'BtnConnect'
    $saved = (Require-Id 'ConnectHost').GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
    if ($saved -ne $ConnectEndpoint) { throw 'Successful endpoint was not remembered.' }
    Invoke-Id 'CloseButton'
    Wait-For { $null -eq (Find-Id 'ConnectHost') } 'Dialog did not close after cancellation.'

    Navigate (U '\u4EEA\u8868\u76D8')
    Wait-For {
        $model = (Require-Id 'TxtHeroModel').Current.Name
        return $model -and $model -notmatch (U '\u7B49\u5F85|\u8FDE\u63A5\u8BBE\u5907|\u672A\u8FDE\u63A5|\u6B63\u5728')
    } 'Dashboard did not receive device identity.' 45
    Write-Output "DASHBOARD PASS: $((Require-Id 'TxtHeroModel').Current.Name)"
    Navigate (U '\u8F6F\u4EF6\u7BA1\u7406')
    Wait-For { (Require-Id 'TxtDevice').Current.Name.Contains($ConnectEndpoint) } 'Software manager did not recognize the connected endpoint.' 30
    Wait-For { (Require-Id 'TxtAppCount').Current.Name -match '\d' } 'Software manager did not finish enumerating applications.' 30
    Write-Output "SOFTWARE PASS: $((Require-Id 'TxtAppCount').Current.Name)"
    Write-Output 'WIRELESS SMOKE PASS: validation, busy deferral, timeout, real connection, remembered address, dashboard and software enumeration. No pairing, flash, install, reboot or device write actions were executed.'
}
finally {
    try {
        if ($p -and -not $p.HasExited) {
            [void]$p.CloseMainWindow()
            if (-not $p.WaitForExit(10000)) { throw 'Test process did not exit; isolated settings retained.' }
        }
        if (-not $p -or $p.HasExited) {
            $key = "HKCU:\Software\Tobatools\UiTests\$id"
            if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Recurse }
        }
    }
    finally { $env:TOBATOOLS_TEST_SETTINGS_ID = $previousScope }
}
