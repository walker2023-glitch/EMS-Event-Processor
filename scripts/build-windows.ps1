$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
python -m PyInstaller --noconfirm --clean ems-event-processor.spec
if ($LASTEXITCODE -ne 0) { throw "Executable build failed" }
Write-Host 'Executable: dist/EMS Event Processor/EMS Event Processor.exe'
