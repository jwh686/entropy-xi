# Daily job for Windows Task Scheduler: refresh data, settle, predict, export site data.
# Mondays also rebuild + retrain walk-forward models + backtest.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null
$log = Join-Path $root ("logs\daily_{0:yyyyMMdd}.log" -f (Get-Date))

if ((Get-Date).DayOfWeek -eq "Monday") {
    & $py -X utf8 -u -m entropy_xi build *>> $log
    & $py -X utf8 -u -m entropy_xi train *>> $log
    & $py -X utf8 -u -m entropy_xi backtest *>> $log
}
& $py -X utf8 -u -m entropy_xi daily *>> $log
