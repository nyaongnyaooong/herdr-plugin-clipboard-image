$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$herdr = if ($env:HERDR_BIN_PATH) { $env:HERDR_BIN_PATH } else { "herdr" }

function Notify([string]$title, [string]$body) {
    & $herdr notification show $title --body $body --sound none | Out-Null
}

function Send-PaneText([string]$pane, [string]$text) {
    & $herdr pane send-text $pane $text
    if ($LASTEXITCODE -ne 0) {
        Notify "이미지 붙여넣기" "입력창에 넣지 못했습니다"
        exit $LASTEXITCODE
    }
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Get-StageDir {
    $dir = Join-Path $env:TEMP "herdr-clipboard-images"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $cutoff = (Get-Date).AddDays(-2)
    Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        Remove-Item -Force -ErrorAction SilentlyContinue
    return $dir
}

function Get-ClipboardImagePath {
    $dir = Get-StageDir
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $image = $null
    for ($i = 0; $i -lt 5; $i++) {
        try {
            $image = [System.Windows.Forms.Clipboard]::GetImage()
            break
        } catch {
            Start-Sleep -Milliseconds 40
        }
    }
    if ($image) {
        $path = Join-Path $dir "clip-$stamp.png"
        $image.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
        $image.Dispose()
        return $path
    }
    try {
        if ([System.Windows.Forms.Clipboard]::ContainsFileDropList()) {
            foreach ($file in [System.Windows.Forms.Clipboard]::GetFileDropList()) {
                if ($file -match '\.(png|jpe?g|gif|webp|bmp|tiff?)$' -and (Test-Path -LiteralPath $file)) {
                    $ext = [System.IO.Path]::GetExtension($file)
                    $path = Join-Path $dir "clip-$stamp$ext"
                    Copy-Item -LiteralPath $file -Destination $path
                    return $path
                }
            }
        }
    } catch {
    }
    return $null
}

$pane = $env:HERDR_PANE_ID
if (-not $pane -and $env:HERDR_PLUGIN_CONTEXT_JSON) {
    $context = $env:HERDR_PLUGIN_CONTEXT_JSON | ConvertFrom-Json
    $pane = $context.focused_pane_id
}
if (-not $pane) {
    Notify "이미지 붙여넣기" "포커스된 창이 없습니다"
    exit 1
}

$imagePath = Get-ClipboardImagePath
if ($imagePath) {
    $shown = ($imagePath -replace '\\', '/')
    Send-PaneText $pane " $shown "
    exit 0
}

$text = $null
try {
    if ([System.Windows.Forms.Clipboard]::ContainsText()) {
        $text = [System.Windows.Forms.Clipboard]::GetText()
    }
} catch {
}
if ($text) {
    Send-PaneText $pane $text
    exit 0
}

& $herdr pane send-keys $pane "ctrl+v"
exit $LASTEXITCODE
