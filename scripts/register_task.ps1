# Registers a daily Windows scheduled task that runs scripts\run_daily.ps1.
# Usage (PowerShell):  .\scripts\register_task.ps1 -Time "11:00"
# Remove later with:   Unregister-ScheduledTask -TaskName "EntropyXI-Daily" -Confirm:$false
param([string]$Time = "11:00")
$script = Join-Path $PSScriptRoot "run_daily.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "EntropyXI-Daily" -Action $action -Trigger $trigger -Settings $settings `
    -Description "熵锋奕 Entropy XI daily update" -Force
