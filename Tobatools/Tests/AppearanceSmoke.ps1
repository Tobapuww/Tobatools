param(
    [string]$ExePath = "$PSScriptRoot\..\bin\material-verification\Tobatools.exe",
    [string]$CaptureDirectory = ''
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class AppearanceSmokeWindow {
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hwnd);
}
'@
$script:p = $null
$script:window = $null
$original = $null
$failure = $null
$restoreFailure = $null
$cleanupFailure = $null
$previousTestSettingsId = [Environment]::GetEnvironmentVariable('TOBATOOLS_TEST_SETTINGS_ID', 'Process')
$testSettingsId = [Guid]::NewGuid().ToString('N')
$testRegistryPath = "Software\Tobatools\UiTests\$testSettingsId"
$isolationInitialized = $false
function U([string]$text) { [regex]::Unescape($text) }
function Wait-Until([scriptblock]$condition, [string]$message, [int]$seconds = 10) {
    $deadline = [DateTime]::UtcNow.AddSeconds($seconds)
    do {
        if (& $condition) { return }
        [Threading.Thread]::Sleep(100)
    } while ([DateTime]::UtcNow -lt $deadline)
    throw $message
}
function Start-App {
    $script:p = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path $ExePath) -PassThru
    Wait-Until {
        $script:p.Refresh()
        if ($script:p.HasExited) { throw "Application exited: $($script:p.ExitCode)" }
        return $script:p.MainWindowHandle -ne 0
    } 'No application window.' 25
    $script:window = [System.Windows.Automation.AutomationElement]::FromHandle($script:p.MainWindowHandle)
    Wait-Until { $null -ne (Find-Id 'NavView') } 'Main navigation did not load.'
    Set-WindowWidth 1440
}
function Stop-App {
    if ($script:p -and -not $script:p.HasExited) {
        if (-not $script:p.CloseMainWindow()) { throw 'Could not request test instance closure.' }
        if (-not $script:p.WaitForExit(10000)) { throw 'Test instance did not close; it was not force-killed.' }
    }
    $script:window = $null
}
function Set-WindowWidth([int]$width) {
    if (-not [AppearanceSmokeWindow]::SetWindowPos($script:p.MainWindowHandle, [IntPtr]::Zero, 0, 0, $width, 900, 6)) {
        throw 'Could not resize test window.'
    }
    [Threading.Thread]::Sleep(250)
}
function Capture-Window([string]$name) {
    if (-not $CaptureDirectory) { return }
    Add-Type -AssemblyName System.Drawing
    [void][System.IO.Directory]::CreateDirectory($CaptureDirectory)
    [void][AppearanceSmokeWindow]::SetForegroundWindow($script:p.MainWindowHandle)
    [Threading.Thread]::Sleep(500)
    $rect = $script:window.Current.BoundingRectangle
    $image = New-Object System.Drawing.Bitmap([int]$rect.Width, [int]$rect.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($image)
    try {
        $graphics.CopyFromScreen([int]$rect.X, [int]$rect.Y, 0, 0, $image.Size)
        $image.Save((Join-Path $CaptureDirectory "$name.png"), [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally { $graphics.Dispose(); $image.Dispose() }
}
function Find-Id([string]$id) {
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $id)
    return $script:window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
}
function Require-Id([string]$id) {
    # Theme/template transitions can briefly detach UI Automation peers.
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        $element = Find-Id $id
        if ($null -ne $element) { return $element }
        [Threading.Thread]::Sleep(100)
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Required control is missing: $id"
}
function Find-Name([string]$name) {
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $name)
    return $script:window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
}
function Navigate([string]$name) {
    $nav = Require-Id 'NavView'
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $name)
    foreach ($element in $nav.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)) {
        $pattern = $null
        if ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) {
            $pattern.Select()
            Wait-Until { $pattern.Current.IsSelected } "Navigation did not select: $name"
            [Threading.Thread]::Sleep(200)
            Assert-NoDialog
            return
        }
    }
    throw "Navigation item is missing or cannot be selected: $name"
}
function Assert-NoDialog {
    if ($script:p.HasExited) { throw 'Application exited during appearance testing.' }
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'ContentDialog')
    foreach ($dialog in $script:window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)) {
        if (-not $dialog.Current.IsOffscreen) { throw 'Unexpected modal dialog.' }
    }
}
function Open-Settings {
    Navigate (U '\u8BBE\u7F6E')
    Wait-Until { $null -ne (Find-Id 'ToggleLiquidGlass') } 'Settings appearance controls did not load.'
    foreach ($id in @('ComboTheme', 'ToggleLiquidGlass', 'SliderGlassBlur', 'TxtGlassBlur', 'TxtMaterialStatus')) {
        [void](Require-Id $id)
    }
    Wait-Until {
        $status = (Require-Id 'TxtMaterialStatus').Current.Name
        return -not [string]::IsNullOrWhiteSpace($status) -and $status -ne (U '\u6B63\u5728\u8BFB\u53D6\u5916\u89C2\u72B6\u6001\u2026')
    } 'Material status is empty or still loading.'
    if (-not (Require-Id 'ToggleLiquidGlass').Current.IsEnabled) { throw 'Appearance service is unavailable.' }
}
function Get-Glass {
    $pattern = (Require-Id 'ToggleLiquidGlass').GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if ($pattern.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::Indeterminate) { throw 'Glass toggle is indeterminate.' }
    return $pattern.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On
}
function Get-Blur {
    $pattern = (Require-Id 'SliderGlassBlur').GetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern)
    return $pattern.Current.Value
}
function Get-Theme {
    $pattern = (Require-Id 'ComboTheme').GetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern)
    $selected = $pattern.Current.GetSelection()
    if ($selected.Count -ne 1) { throw 'Theme selection is unavailable or ambiguous.' }
    return $selected[0].Current.Name
}
function Set-Glass([bool]$enabled) {
    if ((Get-Glass) -ne $enabled) {
        $pattern = (Require-Id 'ToggleLiquidGlass').GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
        $pattern.Toggle()
    }
    Wait-Until { (Get-Glass) -eq $enabled } "Glass toggle did not update: $enabled"
    if (-not $enabled) {
        Wait-Until { -not (Require-Id 'SliderGlassBlur').Current.IsEnabled } 'Blur slider remains enabled with glass off.'
    }
}
function Set-Blur([int]$amount) {
    $slider = Require-Id 'SliderGlassBlur'
    if (-not $slider.Current.IsEnabled) {
        throw "Blur coverage blocked: effects are unavailable or glass is off. Status: $((Require-Id 'TxtMaterialStatus').Current.Name). This is not a full test pass."
    }
    $pattern = $slider.GetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern)
    if ($pattern.Current.Minimum -ne 0 -or $pattern.Current.Maximum -ne 64 -or $pattern.Current.SmallChange -ne 1) {
        throw 'Blur slider range or step differs from 0..64 / 1 DIP.'
    }
    $pattern.SetValue($amount)
    Wait-Until { (Get-Blur) -eq $amount -and (Require-Id 'TxtGlassBlur').Current.Name -eq "$amount DIP" } "Blur value or DIP label did not update: $amount"
}
function Set-Theme([string]$name) {
    $combo = Require-Id 'ComboTheme'
    $expand = $combo.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
    $expand.Expand()
    [Threading.Thread]::Sleep(150)
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $name)
    foreach ($choice in $script:window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)) {
        $pattern = $null
        if ($choice.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) {
            $pattern.Select()
            Wait-Until { (Get-Theme) -eq $name } "Theme did not update: $name"
            [Threading.Thread]::Sleep(250)
            Assert-NoDialog
            return
        }
    }
    throw "Theme choice is unavailable: $name"
}
function Assert-Appearance([bool]$enabled, [int]$amount, [string]$theme, [bool]$requireEffects = $true) {
    if ((Get-Glass) -ne $enabled) { throw 'Glass preference changed unexpectedly.' }
    if ((Get-Blur) -ne $amount) { throw "Blur preference changed unexpectedly; expected $amount." }
    if ((Require-Id 'TxtGlassBlur').Current.Name -ne "$amount DIP") { throw 'Blur text disagrees with slider.' }
    if ((Get-Theme) -ne $theme) { throw 'Theme preference changed unexpectedly.' }
    $sliderEnabled = (Require-Id 'SliderGlassBlur').Current.IsEnabled
    if (-not $enabled -and $sliderEnabled) { throw 'Blur slider is enabled while glass is off.' }
    if ($enabled -and $requireEffects -and -not $sliderEnabled) {
        throw "Effects unavailable; full coverage cannot pass. Status: $((Require-Id 'TxtMaterialStatus').Current.Name)"
    }
    if ([string]::IsNullOrWhiteSpace((Require-Id 'TxtMaterialStatus').Current.Name)) { throw 'Material status is missing.' }
    Assert-NoDialog
}
$tabs = @('\u4EEA\u8868\u76D8', '\u955C\u50CF\u8F85\u52A9', '\u955C\u50CF\u5DE5\u5382', '\u6295\u5C4F', '\u8F6F\u4EF6\u7BA1\u7406', '\u6587\u4EF6\u7BA1\u7406', '\u57FA\u5E26\u5907\u4EFD', '\u6742\u9879\u5DE5\u5177\u7BB1', '\u8BBE\u7F6E') | ForEach-Object { U $_ }
$sentinels = @('TxtHeroModel', 'TxtDev', '', 'ComboMaxSize', 'TxtSearch', 'TxtPath', 'ChkZip', 'MiscTool_payload', 'ComboTheme')
try {
    $ExePath = (Resolve-Path -LiteralPath $ExePath).Path
    # Each child inherits this process-only value. Existing instances are untouched.
    [Environment]::SetEnvironmentVariable('TOBATOOLS_TEST_SETTINGS_ID', $testSettingsId, 'Process')
    $isolationInitialized = $true
    Write-Output "ISOLATION: HKCU\$testRegistryPath"
    Start-App
    Open-Settings
    $original = @{ Glass = (Get-Glass); Blur = (Get-Blur); Theme = (Get-Theme) }
    if ($original.Glass -ne $false -or $original.Blur -ne 24) {
        # Do not mutate settings if this executable does not honor fresh defaults.
        $original = $null
        throw 'Fresh isolated settings must start with Glass=false and Blur=24; no appearance preferences were changed.'
    }
    Assert-Appearance $false 24 $original.Theme
    Write-Output 'DEFAULTS PASS: fresh isolated settings start with glass off and blur at 24 DIP.'
    Write-Output "SNAPSHOT: isolated glass=$($original.Glass), blur=$($original.Blur), theme=$($original.Theme)"
    Set-Glass $false
    Assert-Appearance $false $original.Blur $original.Theme
    Set-Glass $true
    if (-not (Require-Id 'SliderGlassBlur').Current.IsEnabled) {
        Write-Output "FALLBACK VERIFIED: toggle preference is retained, blur is disabled, status=$((Require-Id 'TxtMaterialStatus').Current.Name)"
        throw 'Full appearance smoke coverage requires a Windows session with composition/transparency effects available. Slider, theme, and restart coverage is incomplete.'
    }
    foreach ($width in @(1440, 900)) {
        Set-WindowWidth $width
        foreach ($theme in @((U '\u6D45\u8272'), (U '\u6DF1\u8272'))) {
            Set-Theme $theme
            foreach ($amount in @(0, 24, 64)) {
                Set-Glass $true
                Set-Blur $amount
                Assert-Appearance $true $amount $theme
                $themeTag = if ($theme -eq (U '\u6D45\u8272')) { 'light' } else { 'dark' }
                Capture-Window "settings-$themeTag-$width-blur$amount"
                Set-Glass $false
                Assert-Appearance $false $amount $theme
                if ($amount -eq 24) { Capture-Window "settings-$themeTag-$width-mica" }
                Set-Glass $true
                Assert-Appearance $true $amount $theme
                Write-Output "CONTROLS PASS: width=$width, theme=$theme, blur=$amount, toggle off/on."
            }
            for ($index = 0; $index -lt $tabs.Count; $index++) {
                Navigate $tabs[$index]
                if ($sentinels[$index]) {
                    $id = $sentinels[$index]
                    Wait-Until { $null -ne (Find-Id $id) } "Page content missing: $($tabs[$index]) ($id)"
                }
                else {
                    Wait-Until { $null -ne (Find-Name (U 'Payload.bin \u89E3\u5305')) } 'Image factory tool entry is missing.'
                }
                Assert-NoDialog
                if ($index -eq 0) { Capture-Window "dashboard-$themeTag-$width-glass" }
                Open-Settings
                Assert-Appearance $true 64 $theme
                # Exercise the controls after re-entry, rather than checking stale values only.
                Set-Glass $false
                Set-Glass $true
                Set-Blur 24
                Set-Blur 64
                Assert-Appearance $true 64 $theme
                Write-Output "NAVIGATION PASS: $($tabs[$index]) and settings return, width=$width, theme=$theme."
            }
        }
    }
    foreach ($amount in @(0, 24, 64)) {
        foreach ($enabled in @($false, $true)) {
            Set-Glass $true
            Set-Blur $amount
            Set-Glass $enabled
            $theme = if ($enabled) { U '\u6DF1\u8272' } else { U '\u6D45\u8272' }
            Set-Theme $theme
            Assert-Appearance $enabled $amount $theme
            Stop-App
            Start-App
            Open-Settings
            Assert-Appearance $enabled $amount $theme
            Write-Output "RESTART PASS: glass=$enabled, blur=$amount, theme=$theme."
        }
    }
    Stop-App
    & "$PSScriptRoot\ToolNavigationSmoke.ps1" -ExePath $ExePath
    if (-not $?) { throw 'Inline tool navigation failed with glass enabled.' }
    Start-App
    Open-Settings
    Assert-Appearance $true 64 (U '\u6DF1\u8272')
}
catch {
    $failure = $_
    if ($script:window) {
        Write-Output 'DIAGNOSTIC: appearance controls after failure'
        foreach ($item in $script:window.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) {
            if ($item.Current.AutomationId -or $item.Current.ControlType.ProgrammaticName -eq 'ControlType.Window') {
                Write-Output "$($item.Current.ControlType.ProgrammaticName) id=$($item.Current.AutomationId) name=$($item.Current.Name)"
            }
        }
    }
}
finally {
    try {
        if ($null -ne $original) {
            if ($null -eq $script:p -or $script:p.HasExited) { Start-App }
            Open-Settings
            $blurRestoreError = $null
            try {
                if ((Get-Blur) -ne $original.Blur) {
                    Set-Glass $true
                    Set-Blur $original.Blur
                }
            }
            catch { $blurRestoreError = $_ }
            finally {
                try { Set-Glass $original.Glass }
                finally { Set-Theme $original.Theme }
            }
            if ($blurRestoreError) { throw $blurRestoreError }
            Assert-Appearance $original.Glass $original.Blur $original.Theme $false
            Stop-App
            Start-App
            Open-Settings
            Assert-Appearance $original.Glass $original.Blur $original.Theme $false
            Write-Output 'RESTORE PASS: original isolated glass, blur, and theme preferences restored and verified after restart.'
        }
    }
    catch { $restoreFailure = $_ }
    finally {
        try {
            try { Stop-App }
            catch {
                # Only terminate the process object launched by this test, never a named process group.
                Write-Warning "Graceful test-instance shutdown failed: $_"
                if ($script:p -and -not $script:p.HasExited) {
                    $script:p.Kill()
                    if (-not $script:p.WaitForExit(10000)) { throw 'Test instance did not terminate; isolated registry key retained.' }
                }
                if ($null -eq $restoreFailure) { $restoreFailure = $_ }
            }
            if ($script:p -and -not $script:p.HasExited) {
                throw 'Test instance remains running; isolated registry key retained.'
            }
            if ($isolationInitialized) {
                # Delete only this invocation's GUID leaf after its final process has exited.
                [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($testRegistryPath, $false)
                Write-Output "CLEANUP PASS: removed HKCU\$testRegistryPath; existing application instances were not touched."
            }
        }
        catch { $cleanupFailure = $_ }
        finally {
            try {
                [Environment]::SetEnvironmentVariable('TOBATOOLS_TEST_SETTINGS_ID', $previousTestSettingsId, 'Process')
                Write-Output 'ENVIRONMENT RESTORED: previous process-level TOBATOOLS_TEST_SETTINGS_ID value restored.'
            }
            catch {
                if ($cleanupFailure) { Write-Warning "Registry/process cleanup failure: $cleanupFailure" }
                $cleanupFailure = $_
            }
        }
    }
}
if ($cleanupFailure) {
    if ($failure) { Write-Warning "Original test failure: $failure" }
    if ($restoreFailure) { Write-Warning "Isolated preference restoration failure: $restoreFailure" }
    throw "Appearance isolation cleanup failed: $cleanupFailure. Test key: HKCU\$testRegistryPath"
}
if ($restoreFailure) {
    if ($failure) { Write-Warning "Original test failure: $failure" }
    throw "Appearance cleanup/restoration failed: $restoreFailure. Original isolated preferences: glass=$($original.Glass), blur=$($original.Blur), theme=$($original.Theme)"
}
if ($failure) { throw $failure }
Write-Output 'APPEARANCE SMOKE PASS: isolated defaults, controls, nine tabs, two widths, light/dark themes, persistence, preference restoration, and isolation cleanup. No production preferences or device action buttons were touched. Material rendering still requires visual inspection.'
