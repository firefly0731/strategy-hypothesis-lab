# Supervisor for the order-book collector (stage OB): restarts it 10 s after any exit.
$ErrorActionPreference = "Continue"
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $repo
$env:PYTHONPATH = $repo
$py = "C:\Users\smile-user\.venvs\shl-py312\Scripts\python.exe"
$log = "C:\Users\smile-user\md_local\ob_logs"
New-Item -ItemType Directory -Force $log | Out-Null
while ($true) {
    Add-Content "$log\supervisor.log" "$(Get-Date -Format o) start"
    & $py -m crypto_mm.collector --config mm_tick\collector_ob.toml *>> "$log\collector.log"
    Add-Content "$log\supervisor.log" "$(Get-Date -Format o) exit $LASTEXITCODE"
    Start-Sleep -Seconds 10
}
