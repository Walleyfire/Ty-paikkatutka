$ErrorActionPreference = "Stop"
$wrapper = Join-Path $PSScriptRoot "TARKISTA_AUTOMAATTISESTI.bat"
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/d /c `"`"$wrapper`"`""
$trigger = New-ScheduledTaskTrigger -Daily -At "09:00"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Unregister-ScheduledTask `
    -TaskName "Miikan tyonhakuagentti" `
    -Confirm:$false `
    -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName "Tyopaikkatutka" `
    -Description "Keraa, pisteyttaa ja tallentaa sopivia tyopaikkailmoituksia." `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force | Out-Null
Write-Host "Ajastus luotiin onnistuneesti."
