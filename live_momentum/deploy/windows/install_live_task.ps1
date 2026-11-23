# Registers the LIVE trader as a per-user scheduled task (REAL ORDERS). Run this only after:
#   1. USDT is in the futures wallet (USDT-margined contracts need USDT margin)
#   2. you approved Phase 3 and set the approval token yourself, e.g.
#      [Environment]::SetEnvironmentVariable("LIVE_MOMENTUM_ACK", "phase3-live:2026-12-20", "User")
# Remove with: Unregister-ScheduledTask LiveMomentumLive -Confirm:$false
$here = $PSScriptRoot
$ps = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$a = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$here\run_live.ps1`""
Register-ScheduledTask -TaskName LiveMomentumLive -Action $a -Settings $set -Force `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) | Out-Null
Get-ScheduledTask LiveMomentumLive | Select-Object TaskName, State
