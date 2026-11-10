$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskCacheBase = 'D:\AI_Cache'
$env:TEMP = Join-Path $taskCacheBase 'temp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $taskCacheBase 'pip'
$env:HF_HOME = Join-Path $taskCacheBase 'huggingface'
$env:HF_HUB_OFFLINE = '0'
$env:TRANSFORMERS_OFFLINE = '0'
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run setup.ps1 first' }
if (-not (Test-Path -LiteralPath '.venv-omni/Scripts/python.exe')) {
    py -3.10 -m venv .venv-omni
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 is required' }
}
$python = Join-Path $PSScriptRoot '.venv-omni/Scripts/python.exe'
$taskTorchWheel = Join-Path $taskCacheBase 'wheels/torch-2.8.0+cu128-cp310-cp310-win_amd64.whl'
if (Test-Path -LiteralPath $taskTorchWheel) {
    & $python -m pip install $taskTorchWheel
    if ($LASTEXITCODE -ne 0) { throw 'Cached PyTorch installation failed' }
}
& $python -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw 'OmniVoice PyTorch installation failed' }
$constraints = @()
if (Test-Path -LiteralPath 'requirements-omnivoice-installed.txt') { $constraints = @('-c', 'requirements-omnivoice-installed.txt') }
& $python -m pip install @constraints -r requirements-omnivoice.txt
if ($LASTEXITCODE -ne 0) { throw 'OmniVoice dependencies installation failed' }
if (-not (Test-Path -LiteralPath 'vendor/omnivoice/.git')) {
    git clone https://github.com/k2-fsa/OmniVoice.git vendor/omnivoice
    if ($LASTEXITCODE -ne 0) { throw 'OmniVoice source download failed' }
}
git -C vendor/omnivoice checkout --detach 08be0b4ccbac3e13e374e86fbfead4b4cac343e2
if ($LASTEXITCODE -ne 0) { throw 'Cannot select pinned OmniVoice revision' }
& $python -m pip install --no-deps ./vendor/omnivoice
if ($LASTEXITCODE -ne 0) { throw 'OmniVoice installation failed' }
& ./.venv/Scripts/python.exe -X utf8 -m app.download omnivoice
if ($LASTEXITCODE -ne 0) { throw 'OmniVoice model download failed' }
if (-not (Test-Path -LiteralPath 'voices/reference.json')) {
    & ./.venv/Scripts/python.exe -X utf8 -m app.benchmark --make-reference
    if ($LASTEXITCODE -ne 0) { throw 'Install Vachana first to generate the reference voice' }
}
& $python -X utf8 -c "import app.omni_worker; from omnivoice import OmniVoice; import torch, transformers, pythainlp, json; from pathlib import Path; Path('.venv-omni/runtime.json').write_text(json.dumps({'source_revision':'08be0b4ccbac3e13e374e86fbfead4b4cac343e2','torch':torch.__version__,'transformers':transformers.__version__,'pythainlp':pythainlp.__version__}),encoding='utf-8')"
if ($LASTEXITCODE -ne 0) { throw 'OmniVoice import check failed' }
& $python -m pip freeze --exclude omnivoice | ForEach-Object { if ($_ -match '^torch @ file:') { 'torch==2.8.0+cu128' } else { $_ } } | Set-Content -Encoding utf8 requirements-omnivoice-installed.txt
Write-Host 'OmniVoice installed on D. Restart start.ps1 and select OmniVoice in the extension.'
