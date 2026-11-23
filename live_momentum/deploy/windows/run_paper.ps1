# Supervisor for the Phase 1 paper trader: restarts it 10 s after any exit,
# except exit code 2 (Binance access restricted: stop, do not route around it).
$ErrorActionPreference = "Continue"
$repo = (Resolve-Path "$PSScriptRoot\..\..\..").Path
Set-Location $repo
$env:PYTHONPATH = $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"
$cfg = "live_momentum\deploy\windows\config.paper.toml"
New-Item -ItemType Directory -Force "live_momentum\runtime\log" | Out-Null
$sup = "live_momentum\runtime\log\supervisor.log"
while ($true) {
    Add-Content $sup "$(Get-Date -Format o) start"
    & $py -m live_momentum.run_paper --config $cfg --equity 10000 *>> "live_momentum\runtime\log\stdout.log"
    $code = $LASTEXITCODE
    Add-Content $sup "$(Get-Date -Format o) exit $code"
    if ($code -eq 2) { Add-Content $sup "access restricted: supervisor stops"; break }
    Start-Sleep -Seconds 10
}
