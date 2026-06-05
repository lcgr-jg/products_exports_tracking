# Use the workspace .venv (same kernel as the notebook — has kpler-sdk).
$RootVenv = Join-Path $PSScriptRoot ".." ".venv" "Scripts" "python.exe"
if (-not (Test-Path $RootVenv)) {
    Write-Error "Expected $RootVenv — create/install the Coding\.venv first."
    exit 1
}
Set-Location $PSScriptRoot
& $RootVenv -m export_pace.app
