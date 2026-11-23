# Registers two per-user scheduled tasks (no admin needed). They run only while this user is logged on.
#   LiveMomentumPaper  : at logon, the paper trader supervisor (run_paper.ps1)
#   LiveMomentumReport : daily 06:20 and 21:00 KST = 21:20 and 12:00 UTC (KST has no DST)
# Remove with: Unregister-ScheduledTask LiveMomentumPaper,LiveMomentumReport -Confirm:$false
$here = $PSScriptRoot
$ps = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$p = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$here\run_paper.ps1`""
Register-ScheduledTask -TaskName LiveMomentumPaper -Action $p -Settings $set -Force `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) | Out-Null
$r = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$here\run_report.ps1`""
$rset = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName LiveMomentumReport -Action $r -Settings $rset -Force `
    -Trigger @((New-ScheduledTaskTrigger -Daily -At "06:20"), (New-ScheduledTaskTrigger -Daily -At "21:00")) | Out-Null
Get-ScheduledTask LiveMomentumPaper, LiveMomentumReport | Select-Object TaskName, State
