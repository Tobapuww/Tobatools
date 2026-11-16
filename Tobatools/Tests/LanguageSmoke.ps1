param([string]$ExePath = "$PSScriptRoot\..\bin\languages-verification\Tobatools.exe", [switch]$StartupOnly, [string]$CaptureDirectory = '')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class LanguageSmokeWindow {
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int height, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
'@
$previousId = $env:TOBATOOLS_TEST_SETTINGS_ID
$id = [Guid]::NewGuid().ToString('N')
$regPath = "Software\Tobatools\UiTests\$id"
$env:TOBATOOLS_TEST_SETTINGS_ID = $id
$script:p = $null
$script:window = $null
function Start-App {
    $script:p = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path $ExePath) -PassThru
    $until = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $script:p.Refresh()
        if ($script:p.HasExited) { throw "Startup exited: $($script:p.ExitCode)" }
        if ($script:p.MainWindowHandle -ne 0) { break }
        [Threading.Thread]::Sleep(100)
    } while ([DateTime]::UtcNow -lt $until)
    if ($script:p.MainWindowHandle -eq 0) { throw 'Startup timed out.' }
    $script:window = [System.Windows.Automation.AutomationElement]::FromHandle($script:p.MainWindowHandle)
    [void](Require-Id 'NavSettingsItem')
}
function Stop-App {
    if ($script:p -and -not $script:p.HasExited) {
        if (-not $script:p.CloseMainWindow()) { throw 'Test window did not accept close request.' }
        if (-not $script:p.WaitForExit(15000)) { throw 'Test window did not close gracefully.' }
    }
    $script:window = $null
}
function Find-Id([string]$name) {
    $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $name)
    return $script:window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
}
function Require-Id([string]$name) {
    $until = [DateTime]::UtcNow.AddSeconds(8)
    do {
        $el = Find-Id $name
        if ($null -ne $el) { return $el }
        [Threading.Thread]::Sleep(100)
    } while ([DateTime]::UtcNow -lt $until)
    throw "Missing control: $name"
}
function Invoke-Element($el) {
    $pattern = $null
    if ($el.TryGetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern,[ref]$pattern)) { $pattern.ScrollIntoView() }
    $pattern = $null
    if ($el.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$pattern)) { $pattern.Select() }
    elseif ($el.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)) { $pattern.Invoke() }
    else { throw "Not actionable: $($el.Current.AutomationId)" }
    [Threading.Thread]::Sleep(300)
}
function Select-Combo([string]$id, [string]$name) {
    $combo = Require-Id $id
    $pattern = $null
    if ($combo.TryGetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern,[ref]$pattern)) { $pattern.ScrollIntoView() }
    $combo.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand()
    [Threading.Thread]::Sleep(200)
    $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$name)
    foreach ($el in $script:window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)) {
        $pattern = $null
        if ($el.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$pattern)) {
            $pattern.Select()
            [Threading.Thread]::Sleep(350)
            return
        }
    }
    throw "Combo choice missing: $id / $name"
}
function Get-Resource([string]$lang, [string]$key) {
    [xml]$xml = Get-Content -LiteralPath "$PSScriptRoot\..\Strings\$lang\Resources.resw" -Raw -Encoding UTF8
    return ($xml.root.data | Where-Object { $_.name -eq $key }).value
}
function Assert-Name([string]$id,[string]$expected) {
    $actual = (Require-Id $id).Current.Name
    if ($actual -ne $expected) { throw "Unexpected text on ${id}: expected '$expected', actual '$actual'" }
}
function Capture([string]$name) {
    if (-not $CaptureDirectory) { return }
    Add-Type -AssemblyName System.Drawing
    [void][System.IO.Directory]::CreateDirectory($CaptureDirectory)
    [void][LanguageSmokeWindow]::SetForegroundWindow($script:p.MainWindowHandle)
    [Threading.Thread]::Sleep(400)
    $rect = $script:window.Current.BoundingRectangle
    $bitmap = New-Object System.Drawing.Bitmap([int]$rect.Width,[int]$rect.Height)
    $g = [System.Drawing.Graphics]::FromImage($bitmap)
    try { $g.CopyFromScreen([int]$rect.X,[int]$rect.Y,0,0,$bitmap.Size); $bitmap.Save((Join-Path $CaptureDirectory "$name.png")) }
    finally { $g.Dispose(); $bitmap.Dispose() }
}
try {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($regPath)
    $key.SetValue('appearance/language','zh-CN'); $key.Close()
    Start-App
    Assert-Name 'NavRootItem' (Get-Resource 'zh-CN' 'NavRoot')
    Invoke-Element (Require-Id 'NavSettingsItem')
    [void](Require-Id 'ComboLanguage')
    Write-Output 'STARTUP PASS: desktop translation catalog and language selector loaded.'
    if ($StartupOnly) { return }
    Stop-App
    $tabs = @{'NavDashboard'='NavDashboard';'NavRootItem'='NavRoot';'NavImageFactory'='NavImageFactory';'NavScrcpy'='NavScrcpy';'NavSoftware'='NavSoftware';'NavFiles'='NavFiles';'NavBackup'='NavBackup';'NavMisc'='NavMisc';'NavSettingsItem'='NavSettings'}
    foreach ($lang in @('zh-CN','en-US','ru-RU')) {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($regPath,$true)
        $key.SetValue('appearance/language',$lang); $key.Close()
        Start-App
        foreach ($width in @(1440,900)) {
            [void][LanguageSmokeWindow]::SetWindowPos($script:p.MainWindowHandle,[IntPtr]::Zero,0,0,$width,900,6)
            foreach ($theme in @('SettingsThemeLight','SettingsThemeDark')) {
                Invoke-Element (Require-Id 'NavSettingsItem')
                Select-Combo 'ComboTheme' (Get-Resource $lang $theme)
                foreach ($nav in $tabs.Keys) {
                    Assert-Name $nav (Get-Resource $lang $tabs[$nav])
                    Invoke-Element (Require-Id $nav)
                    if ($script:p.HasExited) { throw "App exited on $lang / $nav" }
                    $dialogCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty,'ContentDialog')
                    foreach ($dlg in $script:window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$dialogCond)) {
                        if (-not $dlg.Current.IsOffscreen) { throw "Unexpected modal on $nav" }
                    }
                    # Never inspect user device/app names; check static page labels separately in catalog tests.
                }
                Invoke-Element (Require-Id 'NavSettingsItem')
                Capture "$lang-$width-$theme-settings"
                Invoke-Element (Require-Id 'NavDashboard')
                Capture "$lang-$width-$theme-dashboard"
                Write-Output "NAVIGATION PASS: $lang / width=$width / $theme / nine tabs."
            }
        }
        Invoke-Element (Require-Id 'NavSettingsItem')
        $next = if ($lang -eq 'en-US') { 'ru-RU' } else { 'en-US' }
        Select-Combo 'ComboLanguage' (Get-Resource $lang $(if ($next -eq 'en-US') {'SettingsLanguageEnUS'} else {'SettingsLanguageRuRU'}))
        Assert-Name 'NavSettingsItem' (Get-Resource $lang 'NavSettings')
        $notice = Require-Id 'InfoBarRestart'
        if ($notice.Current.IsOffscreen) { throw 'Restart notice is hidden.' }
        # Return to settings while a restart is pending: notice must persist.
        Invoke-Element (Require-Id 'NavDashboard')
        Invoke-Element (Require-Id 'NavSettingsItem')
        [void](Require-Id 'InfoBarRestart')
        Stop-App
        Start-App
        Assert-Name 'NavSettingsItem' (Get-Resource $next 'NavSettings')
        Write-Output "LANGUAGE CHANGE PASS: $lang -> $next, current UI unchanged, new language after restart."
        Stop-App
    }
    Write-Output 'LANGUAGE SMOKE PASS: three languages, two widths, two themes, safe deferred switching. No device-write operations invoked.'
}
finally {
    try { Stop-App }
    finally {
        [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($regPath,$false)
        $env:TOBATOOLS_TEST_SETTINGS_ID = $previousId
    }
}
