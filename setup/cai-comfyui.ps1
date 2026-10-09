<#
Cài công cụ tự vẽ ảnh: ComfyUI portable (bản cho card NVIDIA) + model SDXL-Lightning 4 bước của ByteDance.
Bấm đúp cai-comfyui.cmd ở thư mục gốc (hoặc: powershell -NoProfile -ExecutionPolicy Bypass -File setup\cai-comfyui.ps1)

  1. kiểm tra card NVIDIA (driver >= 580 vì bản portable dùng PyTorch CUDA 13, VRAM >= 8 GB), ổ đĩa, 7-Zip
  2. tải 2 file (~9 GB) vào engines\_downloads: rớt mạng thì tự tải tiếp từ chỗ dở, tối đa 30 lần
  3. so mã SHA-256 với bản đã thử (đúng từng byte mới cài)
  4. giải nén ComfyUI vào engines\ComfyUI_windows_portable, đặt model vào ComfyUI\models\checkpoints
Chạy lại được: file đã tải đủ và đúng mã thì không tải lại; đã cài thì bỏ qua.
Xong thì bật bằng chay-comfyui.cmd (cổng 8188) và đặt "image_source": "comfyui" trong kịch bản (xem README).

Tham số: -GiuFileTai  giữ lại file .7z sau khi giải nén (mặc định xoá để lấy lại ~2 GB).
#>
param([switch]$GiuFileTai)

$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$Root = Split-Path -Parent $PSScriptRoot
$Engines = Join-Path $Root "engines"
$Downloads = Join-Path $Engines "_downloads"
$Comfy = Join-Path $Engines "ComfyUI_windows_portable"
$Checkpoints = Join-Path $Comfy "ComfyUI\models\checkpoints"

# Hai file đã tải và chạy thử 05–06/10/2026 (ComfyUI v0.38.0, torch 2.14 + CUDA 13).
$Archive = @{ Name = "ComfyUI_windows_portable_nvidia.7z"; Size = 1994326521
              Sha256 = "8F137EAC345707FD7E42BCF8E29377415243011CA15522A86AED6C77331FBD56"
              Url = "https://github.com/Comfy-Org/ComfyUI/releases/download/v0.38.0/ComfyUI_windows_portable_nvidia.7z" }
$Model = @{ Name = "sdxl_lightning_4step.safetensors"; Size = 6938040682
            Sha256 = "E0D996EE0013E79D9D3561F50FCAFB9A17E3FF07B780358E3B66D67932C4D490"
            Url = "https://huggingface.co/ByteDance/SDXL-Lightning/resolve/main/sdxl_lightning_4step.safetensors" }

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "  [ok] $text" -ForegroundColor Green }
function Info($text) { Write-Host "       $text" -ForegroundColor Gray }
function Warn($text) { Write-Host "  [!]  $text" -ForegroundColor Yellow }
function Stop-With($text) { Write-Host "  [--] $text" -ForegroundColor Red; exit 1 }

function Get-Size([string]$Path) {
    if (Test-Path $Path) { return (Get-Item $Path).Length }
    return 0
}

function Get-Verified($File, [string]$Path) {
    # đúng kích thước rồi mới tính SHA-256 (file 7 GB mất khoảng một phút); lưu dấu .ok để lần sau khỏi tính lại
    $mark = "$Path.sha256-ok"
    if ((Get-Size $Path) -ne $File.Size) { return $false }
    if ((Test-Path $mark) -and ((Get-Content $mark -Raw).Trim() -eq $File.Sha256)) { return $true }
    Info "đang kiểm tra mã SHA-256 của $($File.Name)..."
    $hash = (Get-FileHash -Algorithm SHA256 -Path $Path).Hash
    if ($hash -ne $File.Sha256) {
        Move-Item -Force $Path "$Path.sai-ma"
        Stop-With "$($File.Name) sai mã SHA-256 ($hash) - đã đổi tên thành .sai-ma; chạy lại để tải lại"
    }
    Set-Content -Path $mark -Value $File.Sha256
    return $true
}

function Get-File($File, [string]$Path) {
    if (Get-Verified $File $Path) { Ok "$($File.Name) đã tải đủ"; return }
    if ((Get-Size $Path) -gt $File.Size) { Remove-Item -Force $Path }   # lớn hơn bản gốc: hỏng, tải lại từ đầu
    $mb = [math]::Round($File.Size / 1MB)
    Info "tải $($File.Name) ($mb MB) từ $($File.Url)"
    for ($try = 1; $try -le 30; $try++) {
        & curl.exe -L --fail --retry 10 --retry-delay 5 --retry-all-errors -C - -o $Path $File.Url
        if ((Get-Size $Path) -eq $File.Size) { break }
        Warn "lần $try chưa xong ($([math]::Round((Get-Size $Path) / 1MB)) / $mb MB) - 10 giây nữa tải tiếp"
        Start-Sleep -Seconds 10
    }
    if (-not (Get-Verified $File $Path)) { Stop-With "chưa tải đủ $($File.Name) sau 30 lần - kiểm tra mạng rồi chạy lại cai-comfyui.cmd" }
    Ok "$($File.Name) đã tải và đúng mã SHA-256"
}

Write-Host "Cài công cụ tự vẽ ảnh: ComfyUI + SDXL-Lightning" -ForegroundColor White
$modelPath = Join-Path $Checkpoints $Model.Name
$python = Join-Path $Comfy "python_embeded\python.exe"
if ((Test-Path $python) -and ((Get-Size $modelPath) -eq $Model.Size)) {
    Ok "đã cài sẵn ở $Comfy"
    Write-Host "Bật bằng chay-comfyui.cmd rồi đặt `"image_source`": `"comfyui`" trong kịch bản (xem README)." -ForegroundColor Green
    exit 0
}

# 1. Kiểm tra máy --------------------------------------------------------------------------------------------------
Step "1/4 Kiểm tra card đồ hoạ, ổ đĩa, 7-Zip"
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if (-not $smi) {
    Warn "không thấy nvidia-smi: máy không có card NVIDIA hoặc chưa cài driver. Bản portable này chỉ chạy trên card NVIDIA;"
    Warn "không có card thì vẫn làm video bình thường bằng ảnh Pexels (không cần cài phần này)."
    $answer = Read-Host "Vẫn tải tiếp? (c/k)"
    if ($answer -notmatch '^[cCyY]') { exit 1 }
} else {
    $gpu = (& nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits | Select-Object -First 1)
    $name, $driver, $vram = $gpu.Split(",") | ForEach-Object { $_.Trim() }
    Info "card: $name, driver $driver, VRAM $vram MB"
    if ([double]($driver.Split(".")[0]) -lt 580) {
        Warn "driver NVIDIA $driver cũ hơn 580 - ComfyUI bản này (CUDA 13) sẽ không chạy. Tải driver mới ở nvidia.com/drivers"
        Warn "(GeForce Game Ready / Studio cho đúng card), cài xong khởi động lại máy. Vẫn tải được trong lúc chờ."
    } else { Ok "driver $driver (>= 580)" }
    if ([int]$vram -lt 7900) { Warn "VRAM $vram MB < 8 GB: SDXL có thể thiếu bộ nhớ (chạy chậm hoặc lỗi out of memory)" }
    else { Ok "VRAM $vram MB" }
}
$drive = (Get-Item $Root).PSDrive
$freeGB = [math]::Round($drive.Free / 1GB)
if ($freeGB -lt 25) { Warn "ổ $($drive.Name): còn $freeGB GB - cần khoảng 25 GB (2 GB file nén + 12 GB giải nén + 7 GB model)" }
else { Ok "ổ $($drive.Name): còn $freeGB GB" }
$sevenZip = @((Get-Command 7z -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
              (Join-Path $env:ProgramFiles "7-Zip\7z.exe"), (Join-Path ${env:ProgramFiles(x86)} "7-Zip\7z.exe")) |
            Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $sevenZip) { Stop-With "chưa có 7-Zip (giải nén file .7z): chạy  winget install --id 7zip.7zip -e  rồi chạy lại cai-comfyui.cmd" }
Ok "7-Zip  ($sevenZip)"

# 2–3. Tải + kiểm tra mã -------------------------------------------------------------------------------------------
Step "2/4 Tải ComfyUI portable (~1,9 GB) và model SDXL-Lightning 4 bước (~6,5 GB)"
New-Item -ItemType Directory -Force -Path $Downloads | Out-Null
$archivePath = Join-Path $Downloads $Archive.Name
$modelDownload = Join-Path $Downloads $Model.Name
if (-not (Test-Path $python)) { Get-File $Archive $archivePath } else { Ok "ComfyUI đã giải nén sẵn - không cần file nén" }
if ((Get-Size $modelPath) -ne $Model.Size) { Get-File $Model $modelDownload }

# 4. Giải nén + đặt model -----------------------------------------------------------------------------------------------
Step "3/4 Giải nén ComfyUI vào engines\ComfyUI_windows_portable"
if (-not (Test-Path $python)) {
    & $sevenZip x $archivePath "-o$Engines" -y | Out-Host
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $python)) { Stop-With "giải nén lỗi (mã $LASTEXITCODE) - còn trống đủ ổ đĩa không?" }
    Ok "đã giải nén"
    if (-not $GiuFileTai) { Remove-Item -Force $archivePath, "$archivePath.sha256-ok" -ErrorAction SilentlyContinue; Info "đã xoá file nén (lấy lại ~2 GB)" }
} else { Ok "đã có" }

Step "4/4 Đặt model vào ComfyUI\models\checkpoints"
if ((Get-Size $modelPath) -ne $Model.Size) {
    New-Item -ItemType Directory -Force -Path $Checkpoints | Out-Null
    Move-Item -Force $modelDownload $modelPath
    Remove-Item -Force "$modelDownload.sha256-ok" -ErrorAction SilentlyContinue
}
Ok $modelPath

Write-Host ""
Write-Host "Cài xong công cụ tự vẽ ảnh." -ForegroundColor Green
Write-Host "  1. Bấm đúp chay-comfyui.cmd, chờ dòng  To see the GUI go to: http://127.0.0.1:8188  (để cửa sổ mở)" -ForegroundColor Green
Write-Host "  2. Trong kịch bản đặt  `"image_source`": `"comfyui`"  (hoặc IMAGE_SOURCE=comfyui trong .env cho mọi video)" -ForegroundColor Green
Write-Host "  3. Tạo video như bình thường; ảnh đầu tiên ~10 giây (nạp model), sau đó ~3 giây/ảnh trên RTX 4060 8 GB" -ForegroundColor Green
