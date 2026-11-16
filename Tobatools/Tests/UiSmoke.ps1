param([string]$ExePath = "$PSScriptRoot\..\bin\glass-verification\Tobatools.exe")
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class SmokeWindow {
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int width, int height, uint flags);
}
'@
$p = Start-Process -FilePath $ExePath -PassThru
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        if ($p.HasExited) { throw "Application exited during startup: $($p.ExitCode)" }
        $p.Refresh()
        if ($p.MainWindowHandle -ne 0) { break }
        [Threading.Thread]::Sleep(100)
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($p.MainWindowHandle -eq 0) { throw 'No application window was created.' }
    $window = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
    Write-Output "STARTUP PASS: window is available. Process=$($p.Id)"
    $tabs = @('\u4EEA\u8868\u76D8', '\u955C\u50CF\u8F85\u52A9', '\u955C\u50CF\u5DE5\u5382', '\u6295\u5C4F', '\u8F6F\u4EF6\u7BA1\u7406', '\u6587\u4EF6\u7BA1\u7406', '\u57FA\u5E26\u5907\u4EFD', '\u6742\u9879\u5DE5\u5177\u7BB1', '\u8BBE\u7F6E') | ForEach-Object { [regex]::Unescape($_) }
    $sentinels = @('TxtHeroModel', 'TxtDev', '', 'ComboMaxSize', 'TxtSearch', 'TxtPath', 'ChkZip', '', 'ComboTheme')
    foreach ($width in @(1440, 900)) {
        $tabIndex = 0;
        [void][SmokeWindow]::SetWindowPos($p.MainWindowHandle, [IntPtr]::Zero, 0, 0, $width, 820, 6)
        [Threading.Thread]::Sleep(300)
    foreach ($tab in $tabs) {
        $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $tab)
        $matches = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
        $selected = $false
        foreach ($element in $matches) {
            $pattern = $null
            if ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) {
                $pattern.Select()
                $selected = $true
                break
            }
            if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
                $pattern.Invoke()
                $selected = $true
                break
            }
        }
        if (-not $selected) { throw "Navigation item is unavailable: $tab" }
        [Threading.Thread]::Sleep(500)
        $p.Refresh()
        if ($p.HasExited) { throw "Application exited on tab: $tab" }
        $sentinel = $sentinels[$tabIndex++]
        if ($sentinel) {
            $contentCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $sentinel)
            $content = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $contentCondition)
            if ($null -eq $content) { throw "Expected page content is unavailable: $tab ($sentinel)" }
        }
        $dialogCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'ContentDialog')
        $dialog = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $dialogCondition)
        if ($null -ne $dialog -and -not $dialog.Current.IsOffscreen) { throw "Unexpected modal dialog on tab: $tab" }
        Write-Output "NAVIGATION PASS: $tab (width=$width)"
    }
    }
    $comboCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'ComboTheme')
    $combo = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $comboCondition)
    if ($null -eq $combo) { throw 'Theme selector is unavailable.' }
    $selection = $combo.GetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern)
    $originalTheme = $selection.Current.GetSelection()[0].Current.Name
    function Select-Theme([string]$name) {
        $expand = $combo.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
        $expand.Expand()
        [Threading.Thread]::Sleep(100)
        $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $name)
        $choices = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
        foreach ($choice in $choices) {
            $pattern = $null
            if ($choice.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) {
                $pattern.Select()
                [Threading.Thread]::Sleep(200)
                return
            }
        }
        throw "Theme choice is unavailable: $name"
    }
    try {
        foreach ($name in @('\u6D45\u8272', '\u6DF1\u8272', '\u8DDF\u968F\u7CFB\u7EDF')) {
            Select-Theme ([regex]::Unescape($name))
            if ($p.HasExited) { throw 'Application exited while switching theme.' }
            Write-Output "THEME SWITCH PASS: $name"
        }
    }
    finally { Select-Theme $originalTheme }
    Write-Output 'Navigation and theme-switch smoke tests completed. Original theme restored. No device action buttons were invoked.'
}
finally {
    if (-not $p.HasExited) { [void]$p.CloseMainWindow() }
}
