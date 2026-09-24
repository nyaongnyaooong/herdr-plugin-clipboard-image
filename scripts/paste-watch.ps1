$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Find-Python {
    $candidates = @()
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps") {
        $candidates += $cmd.Source
    }
    $candidates += @(
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
    )
    foreach ($path in $candidates) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        & $path -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"
        if ($LASTEXITCODE -eq 0) { return $path }
    }
    throw "Python 3.9+ was not found"
}

$python = Find-Python
$script = Join-Path $PSScriptRoot "paste_watch.py"
$state = Join-Path $env:LOCALAPPDATA "herdr\clipboard-image"
New-Item -ItemType Directory -Force -Path $state | Out-Null
$pidFile = Join-Path $state "paste.pid"
if (Test-Path -LiteralPath $pidFile) {
    $old = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($old -match "^\d+$") {
        Stop-Process -Id ([int]$old) -Force -ErrorAction SilentlyContinue
    }
}
$proc = Start-Process -FilePath $python -ArgumentList @($script) -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $pidFile -Value $proc.Id -Encoding ascii
