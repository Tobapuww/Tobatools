param([string]$ExePath = "$PSScriptRoot\..\bin\glass-verification\Tobatools.exe")
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ToolSmokeWindow {
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int width, int height, uint flags);
}
'@
$script:p = $null
$script:window = $null
$originalBannerName = $null
function U([string]$text) { [regex]::Unescape($text) }
function Start-App {
    $script:p = Start-Process -FilePath $ExePath -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        $script:p.Refresh()
        if ($script:p.HasExited) { throw "Application exited: $($script:p.ExitCode)" }
        if ($script:p.MainWindowHandle -ne 0) { break }
        [Threading.Thread]::Sleep(100)
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($script:p.MainWindowHandle -eq 0) { throw 'No application window.' }
    $script:window = [System.Windows.Automation.AutomationElement]::FromHandle($script:p.MainWindowHandle)
    [Threading.Thread]::Sleep(500)
}
function Stop-App {
    if ($script:p -and -not $script:p.HasExited) {
        [void]$script:p.CloseMainWindow()
        if (-not $script:p.WaitForExit(10000)) { throw 'Test instance did not close.' }
    }
}
function Find-Id([string]$id) {
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $id)
    return $script:window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
}
function Is-Visible($element) { return ($null -ne $element -and -not $element.Current.IsOffscreen) }
function Invoke-Element($element) {
    if ($null -eq $element) { throw 'Required element is missing.' }
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern, [ref]$pattern)) { $pattern.ScrollIntoView() }
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) { $pattern.Invoke() }
    elseif ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) { $pattern.Select() }
    else { throw "Element has no invocation pattern: $($element.Current.Name)" }
    [Threading.Thread]::Sleep(350)
}
function Invoke-Name([string]$name, $scope = $script:window) {
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $name)
    $matches = $scope.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    foreach ($element in $matches) {
        $pattern = $null
        if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern) -or
            $element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) {
            Invoke-Element $element
            return
        }
    }
    throw "No actionable element named: $name"
}
function Assert-NoDialog {
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'ContentDialog')
    foreach ($dialog in $script:window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)) {
        if (Is-Visible $dialog) { throw 'Unexpected whole-tool or error modal dialog.' }
    }
}
function Assert-Banner([bool]$collapsed) {
    $toggle = Find-Id 'BannerToggle'
    if (-not (Is-Visible $toggle)) { throw 'Banner toggle is missing outside dashboard.' }
    $expected = if ($collapsed) { U '\u5C55\u5F00\u8BBE\u5907\u680F' } else { U '\u6536\u8D77\u8BBE\u5907\u680F' }
    if ($toggle.Current.Name -ne $expected) { throw "Wrong banner state: $($toggle.Current.Name)" }
    if ((Is-Visible (Find-Id 'BtnConnect')) -eq $collapsed) { throw 'Banner contents do not match toggle state.' }
    $summary = Find-Id 'CompactDeviceSummary'
    if ((Is-Visible $summary) -ne $collapsed) { throw 'Compact summary visibility does not match banner state.' }
    if ($collapsed -and [string]::IsNullOrWhiteSpace($summary.Current.Name)) { throw 'Collapsed banner has no device status.' }
}
function Set-Banner([bool]$collapsed) {
    $expected = if ($collapsed) { U '\u5C55\u5F00\u8BBE\u5907\u680F' } else { U '\u6536\u8D77\u8BBE\u5907\u680F' }
    $toggle = Find-Id 'BannerToggle'
    if ($toggle.Current.Name -ne $expected) { Invoke-Element $toggle }
    Assert-Banner $collapsed
}
function Assert-Dashboard {
    Invoke-Name (U '\u4EEA\u8868\u76D8')
    if (Is-Visible (Find-Id 'BannerToggle')) { throw 'Dashboard exposes banner toggle.' }
    if (Is-Visible (Find-Id 'CompactDeviceSummary')) { throw 'Dashboard exposes compact banner summary.' }
    if (Is-Visible (Find-Id 'BtnConnect')) { throw 'Dashboard exposes banner contents.' }
    if (-not (Is-Visible (Find-Id 'TxtHeroModel'))) { throw 'Dashboard content is missing.' }
}
$imageName = U '\u955C\u50CF\u5DE5\u5382'
$miscName = U '\u6742\u9879\u5DE5\u5177\u7BB1'
try {
    Start-App
    Assert-Dashboard
    Invoke-Name $imageName
    $originalBannerName = (Find-Id 'BannerToggle').Current.Name
    foreach ($state in @($true, $false)) {
        Set-Banner $state
        Assert-Dashboard
        Invoke-Name $imageName
        Assert-Banner $state
        Stop-App
        Start-App
        Assert-Dashboard
        Invoke-Name $imageName
        Assert-Banner $state
        Write-Output "BANNER PASS: collapsed=$state persists across navigation and restart; dashboard remains hidden."
    }
    Set-Banner $false
    # Interrupt an in-flight transition repeatedly; final state must remain coherent.
    for ($i = 0; $i -lt 5; $i++) {
        $pattern = (Find-Id 'BannerToggle').GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $pattern.Invoke()
        [Threading.Thread]::Sleep(60)
    }
    [Threading.Thread]::Sleep(400)
    Assert-Banner $true
    Write-Output 'BANNER RAPID TOGGLE PASS: interrupted transitions settle in the expected state with summary visible.'
    $tools = @('Payload.bin \u89E3\u5305', 'OFP \u89E3\u5305', 'Super \u89E3/\u6253\u5305', 'DTBO \u89E3/\u6253\u5305', '\u5206\u533A\u955C\u50CF\uFF08ext4/erofs\uFF09\u89E3/\u6253\u5305', 'Boot \u89E3/\u6253\u5305', 'DAT/BR \u8F6C\u6362')
    foreach ($width in @(1440, 900)) {
        [void][ToolSmokeWindow]::SetWindowPos($script:p.MainWindowHandle, [IntPtr]::Zero, 0, 0, $width, 820, 6)
        [Threading.Thread]::Sleep(300)
        Set-Banner $true
        foreach ($tool in $tools) {
            Invoke-Name (U $tool)
            $breadcrumb = Find-Id 'ToolBreadcrumb'
            if (-not (Is-Visible $breadcrumb)) { throw "Tool breadcrumb is missing: $tool" }
            if ($null -eq (Find-Id 'ToolSubtitle')) { throw "Tool subtitle is missing: $tool" }
            $editCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)
            if ($null -eq $script:window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editCondition)) { throw "Tool inputs are missing: $tool" }
            if (Is-Visible (Find-Id 'ToolNotice')) { throw "Tool reported a load error: $tool" }
            Assert-NoDialog
            Invoke-Name $imageName $breadcrumb
            if ($null -ne (Find-Id 'ToolBreadcrumb')) { throw 'Breadcrumb failed to navigate to category.' }
            Write-Output "IMAGE TOOL PASS: $tool width=$width; inline content and category return."
        }
        Invoke-Name $miscName
        foreach ($id in @('payload', 'ofp', 'configcheck')) {
            Invoke-Element (Find-Id "MiscTool_$id")
            $breadcrumb = Find-Id 'ToolBreadcrumb'
            if (-not (Is-Visible $breadcrumb)) { throw "Misc breadcrumb missing: $id" }
            Assert-NoDialog
            Invoke-Name $miscName $breadcrumb
            if ($null -eq (Find-Id 'MiscTool_payload')) { throw 'Misc category return failed.' }
            Write-Output "MISC TOOL PASS: $id width=$width."
        }
        Invoke-Name $imageName
    }
    Write-Output 'Tool navigation and banner tests completed. No device write or image processing buttons were invoked.'
}
finally {
    try {
        if ($originalBannerName -and $script:p -and -not $script:p.HasExited) {
            Invoke-Name $imageName
            $toggle = Find-Id 'BannerToggle'
            if ($toggle.Current.Name -ne $originalBannerName) { Invoke-Element $toggle }
            Write-Output 'Original banner preference restored.'
        }
    }
    finally { Stop-App }
}
