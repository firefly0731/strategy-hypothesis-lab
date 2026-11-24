# Daily: convert finished UTC days of raw order-book files to parquet; delete a raw file only
# after its parquet files are verified (user decision 2026-11-25).
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $repo
$env:PYTHONPATH = $repo
& "C:\Users\smile-user\.venvs\shl-py312\Scripts\python.exe" -m mm_tick.ob_compact `
    --raw "C:\Users\smile-user\md_local\ob_raw" --out "C:\Users\smile-user\md_local\ob_pq" --delete-raw `
    *>> "C:\Users\smile-user\md_local\ob_logs\compact.log"
