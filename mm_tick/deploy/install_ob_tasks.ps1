# Per-user scheduled tasks (no admin):
#   MMOrderbookCollector : at logon, the collector supervisor
#   MMOrderbookCompact   : daily 09:40 KST = 00:40 UTC, after the UTC day closes
# Remove with: Unregister-ScheduledTask MMOrderbookCollector,MMOrderbookCompact -Confirm:$false
$here = $PSScriptRoot
$ps = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$c = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$here\run_ob_collector.ps1`""
Register-ScheduledTask -TaskName MMOrderbookCollector -Action $c -Settings $set -Force `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) | Out-Null
$k = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$here\run_ob_compact.ps1`""
$kset = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName MMOrderbookCompact -Action $k -Settings $kset -Force `
    -Trigger (New-ScheduledTaskTrigger -Daily -At "09:40") | Out-Null
Get-ScheduledTask MMOrderbookCollector, MMOrderbookCompact | Select-Object TaskName, State
