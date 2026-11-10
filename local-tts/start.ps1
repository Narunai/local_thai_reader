$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run ./setup.ps1 first' }
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
& ./.venv/Scripts/python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --no-access-log
