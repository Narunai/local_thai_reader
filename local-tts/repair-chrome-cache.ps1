$ErrorActionPreference = 'Stop'

# Run with Chrome fully closed. Relocate disposable disk/code caches only;
# keep profile settings, cookies, passwords, extensions and reading state intact.
if (Get-Process chrome -ErrorAction SilentlyContinue) {
    throw 'Save your web work and close every Chrome window, then run this script again.'
}
$chromeProfile = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\Default'))
$cacheRoot = [IO.Path]::GetFullPath('D:\AI_Cache\chrome-cache\Default')
New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
$movedBytes = 0L
foreach ($cacheName in @('Cache', 'Code Cache')) {
    $source = [IO.Path]::GetFullPath((Join-Path $chromeProfile $cacheName))
    $destination = [IO.Path]::GetFullPath((Join-Path $cacheRoot $cacheName))
    # Check exact absolute paths before any recursive copy/removal.
    if ([IO.Path]::GetDirectoryName($source) -ne $chromeProfile) { throw 'Unsafe Chrome cache path.' }
    if ([IO.Path]::GetDirectoryName($destination) -ne $cacheRoot) { throw 'Unsafe cache destination.' }
    if (-not (Test-Path -LiteralPath $source)) { continue }
    $item = Get-Item -LiteralPath $source -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        if (@($item.Target)[0] -ne $destination) { throw 'Cache is redirected to an unexpected location.' }
        Write-Output "$cacheName is already on D."
        continue
    }
    $children = @(Get-ChildItem -LiteralPath $source -Recurse -Force)
    if ($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
        throw 'Unexpected link inside Chrome cache; refusing to migrate it.'
    }
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    $files = @($children | Where-Object { -not $_.PSIsContainer })
    Write-Output "Copying and verifying $cacheName ($($files.Count) files)..."
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($source.Length).TrimStart('\')
        $targetFile = [IO.Path]::GetFullPath((Join-Path $destination $relative))
        if (-not $targetFile.StartsWith($destination + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'File leaves cache destination.' }
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($targetFile)) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $targetFile -Force
        if ((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash) {
            throw "Cache copy verification failed: $relative"
        }
    }
    if (Get-Process chrome -ErrorAction SilentlyContinue) { throw 'Chrome started during migration. Source cache was kept; close Chrome and rerun.' }
    # Every file has a verified copy on D. Exact source is checked above.
    Remove-Item -LiteralPath $source -Recurse -Force
    New-Item -ItemType Junction -Path $source -Target $destination | Out-Null
    $movedBytes += ($files | Measure-Object Length -Sum).Sum
    Write-Output "$cacheName now points to $destination"
}
Write-Output ('Moved {0:N1} MB of Chrome cache to D.' -f ($movedBytes / 1MB))
Get-PSDrive C,D | Select-Object Name,@{Name='FreeMB';Expression={[math]::Round($_.Free/1MB,1)}}
Write-Output 'Open Chrome, go to chrome://extensions, and Reload Local Thai Reader.'
