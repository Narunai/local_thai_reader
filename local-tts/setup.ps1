param([ValidateSet('vachana','thonburian','openjai')][string]$Profile = 'vachana')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Stop the local TTS server before installing or updating packages/models.'
}
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    py -3.10 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 is required' }
}
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$taskCacheBase = 'D:\AI_Cache'
$taskTemp = Join-Path $taskCacheBase 'temp'
New-Item -ItemType Directory -Force -Path $taskTemp | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
$env:HF_HOME = Join-Path $taskCacheBase 'huggingface'
$env:TORCH_HOME = Join-Path $taskCacheBase 'torch'
$env:PIP_CACHE_DIR = Join-Path $taskCacheBase 'pip'
$constraints = @()
if (Test-Path -LiteralPath 'requirements-installed.txt') { $constraints = @('-c', 'requirements-installed.txt') }
& $python -m pip install @constraints -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
if ($Profile -ne 'vachana') {
    & $python -m pip install @constraints --no-cache-dir torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed' }
    & $python -m pip install @constraints -r requirements-f5.txt
    if ($LASTEXITCODE -ne 0) { throw 'F5 dependency installation failed' }
    New-Item -ItemType Directory -Force -Path vendor | Out-Null
    if (-not (Test-Path 'vendor/thonburian-tts/.git')) {
        git clone https://github.com/biodatlab/thonburian-tts.git vendor/thonburian-tts
        if ($LASTEXITCODE -ne 0) { throw 'FlowTTS download failed' }
    }
    git -C vendor/thonburian-tts checkout --detach 032fe7e51674afe066a98e6d3cf47fc96d04b290
    if ($LASTEXITCODE -ne 0) { throw 'Unable to select the tested FlowTTS revision' }
    git -C vendor/thonburian-tts rev-parse HEAD | Set-Content -Encoding ascii vendor/flowtts-revision.txt
}
& $python -m app.download $Profile
if ($LASTEXITCODE -ne 0) { throw 'Model download failed' }
if ($Profile -ne 'vachana' -and -not (Test-Path -LiteralPath 'voices/reference.json')) {
    & $python -m app.download vachana
    if ($LASTEXITCODE -ne 0) { throw 'Reference voice download failed' }
    & $python -X utf8 -m app.benchmark --make-reference
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic reference generation failed' }
}
& $python -m pip freeze | Set-Content -Encoding utf8 requirements-installed.txt
Write-Host 'Setup complete. Run ./start.ps1. Pairing token is stored in local-tts/.token'
