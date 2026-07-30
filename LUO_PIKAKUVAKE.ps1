param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$appScript = Join-Path $PSScriptRoot "tyopaikkatutka.py"
$iconPath = Join-Path $PSScriptRoot "assets\tyopaikkatutka.ico"

if (-not (Test-Path -LiteralPath $appScript)) {
    throw "tyopaikkatutka.py-tiedostoa ei loytynyt."
}
if (-not (Test-Path -LiteralPath $iconPath)) {
    throw "Tyopaikkatutkan kuvaketta ei loytynyt."
}

$pythonw = (& py -3 -c "import pathlib, sys; print(pathlib.Path(sys.executable).with_name('pythonw.exe'))") |
    Select-Object -First 1
if ($LASTEXITCODE -ne 0 -or -not $pythonw) {
    throw "Python 3:n pythonw.exe-tiedostoa ei loytynyt."
}
$pythonw = ([string]$pythonw).Trim()
if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "Pythonin ikkunakaynnistinta ei loytynyt: $pythonw"
}

$appName = "Ty" + [char]0x00F6 + "paikkatutka"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop ($appName + ".lnk")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "`"$appScript`""
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.IconLocation = $iconPath + ",0"
$shortcut.Description = "Avaa " + $appName
$shortcut.WindowStyle = 1
$shortcut.Save()

if (-not $Quiet) {
    Write-Host ("Pikakuvake luotiin: " + $shortcutPath)
}
