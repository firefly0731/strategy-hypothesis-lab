# Daily paper report for the latest completed session.
$repo = (Resolve-Path "$PSScriptRoot\..\..\..").Path
Set-Location $repo
$env:PYTHONPATH = $repo
New-Item -ItemType Directory -Force "live_momentum\runtime\log" | Out-Null
& (Join-Path $repo ".venv\Scripts\python.exe") -m live_momentum.paper_report `
    --config "live_momentum\deploy\windows\config.paper.toml" *>> "live_momentum\runtime\log\report.log"
