$ErrorActionPreference = "Stop"
$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $appDir "run_pipeline.bat"
$taskName = "IndustryScreenerDailyUpdate"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$runner`"" -WorkingDirectory $appDir
$trigger = New-ScheduledTaskTrigger -Daily -At 8:30AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Update public data for the local industry screener" -Force | Out-Null
Write-Host "Daily update installed: $taskName (08:30)"
Read-Host "Press Enter to close"

