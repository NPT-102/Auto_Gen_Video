<#
Cài đặt video-factory trên Windows 10/11. Bấm đúp cai-dat.cmd ở thư mục gốc (hoặc chạy:
    powershell -NoProfile -ExecutionPolicy Bypass -File setup\cai-dat.ps1)

Làm lần lượt, phần nào đã xong thì bỏ qua — chạy lại bao nhiêu lần cũng được:
  1. kiểm tra phần mềm nền: Git, uv, Node.js ≥ 22, FFmpeg, Chrome
  2. tạo .env từ .env.example (nơi điền key)
  3. thư viện Python của web (uv sync) và các project Node có sẵn trong repo (HyperFrames, Remotion, ELK)
  4. tải 3 repo engine đúng commit đã chạy thử rồi cài thư viện của từng repo
  5. chép key từ .env sang config.toml của MoneyPrinterTurbo
  6. in tình trạng: key, engine nào sẵn sàng
Tự vẽ ảnh bằng AI (ComfyUI + SDXL-Lightning, tải ~9 GB) cài riêng bằng cai-comfyui.cmd.

Tham số: -KiemTra  chỉ in tình trạng, không cài gì.
#>
param([switch]$KiemTra)

$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$script:Problems = @()

# Ba repo engine, ghim đúng commit đã chạy thử với video-factory (bản mới hơn có thể đổi giao diện dòng lệnh).
$Repos = @(
    @{ Name = "MoneyPrinterTurbo"; Url = "https://github.com/harry0703/MoneyPrinterTurbo.git"
       Commit = "ad5496f1b729d1d7e361dd972015d26c08b0e052" },
    @{ Name = "ai-auto-generate-video"; Url = "https://github.com/huytranvan2010/AI-auto-generate-video.git"
       Commit = "66507ab98c8ed81bcfdbc1cc31cc634d068bc127" },
    @{ Name = "pixelle-video"; Url = "https://github.com/ATH-MaaS/Pixelle-Video.git"
       Commit = "848b054e4fae40dabc62ec58e960b573e83793ac" }
)

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "  [ok] $text" -ForegroundColor Green }
function Info($text) { Write-Host "       $text" -ForegroundColor Gray }
function Warn($text) { Write-Host "  [!]  $text" -ForegroundColor Yellow; $script:Problems += $text }

function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$Dir = $Root) {
    Write-Host "  > $Exe $($Arguments -join ' ')" -ForegroundColor DarkGray
    Push-Location $Dir
    try {
        & $Exe @Arguments | Out-Host
        $code = $LASTEXITCODE
    } catch {
        Write-Host "    $($_.Exception.Message)" -ForegroundColor Red
        $code = -1
    } finally { Pop-Location }
    return ($code -eq 0)
}

function Find-Tool([string]$Name) {
    $c = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.Source }
    return $null
}

function Read-DotEnv {
    $values = @{}
    if (Test-Path ".env") {
        foreach ($line in Get-Content ".env" -Encoding UTF8) {
            $t = $line.Trim()
            if ($t -and -not $t.StartsWith("#") -and $t.Contains("=")) {
                $kv = $t.Split([char[]]"=", 2)
                $values[$kv[0].Trim()] = $kv[1].Trim().Trim('"').Trim("'")
            }
        }
    }
    return $values
}

function Find-Chrome($envs) {
    if ($envs["CHROME_PATH"]) { return $envs["CHROME_PATH"] }
    $dirs = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA) | Where-Object { $_ }
    foreach ($d in $dirs) {
        $p = Join-Path $d "Google\Chrome\Application\chrome.exe"
        if (Test-Path $p) { return $p }
    }
    foreach ($d in @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }) {
        $p = Join-Path $d "Microsoft\Edge\Application\msedge.exe"
        if (Test-Path $p) { return $p }
    }
    return $null
}

# Lệnh chạy Python của một venv. Smart App Control có thể chặn launcher .venv\Scripts\python.exe của uv → khi đó chạy
# Python gốc mà venv trỏ tới (dòng home trong pyvenv.cfg) qua factory\pyrun.py, nạp thư viện của venv.
function Get-VenvPython([string]$Venv) {
    $launcher = Join-Path $Venv "Scripts\python.exe"
    try {
        & $launcher -c "pass" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return , @($launcher) }
    } catch { }
    $line = Get-Content (Join-Path $Venv "pyvenv.cfg") | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1
    $pyHome = ($line -replace '^\s*home\s*=\s*', '').Trim()
    return , @((Join-Path $pyHome "python.exe"), "-P", (Join-Path $Root "factory\pyrun.py"), $Venv)
}

function Invoke-VenvPython([string]$Venv, [string[]]$Arguments, [string]$Dir) {
    $py = Get-VenvPython $Venv
    $rest = @()
    if ($py.Length -gt 1) { $rest = $py[1..($py.Length - 1)] }
    return (Invoke-Native $py[0] ($rest + $Arguments) $Dir)
}

function Get-Repo($Repo, [string]$Dir) {
    if (Test-Path (Join-Path $Dir ".git")) {
        $head = (& git -C $Dir rev-parse HEAD 2>$null)
        if ($head -eq $Repo.Commit) { Ok "$($Repo.Name): đã có ở $Dir" }
        else { Info "$($Repo.Name): đã có ở $Dir (commit $head, bản đã thử là $($Repo.Commit)) - giữ nguyên" }
        return $true
    }
    if (Test-Path $Dir) { Warn "$Dir đã có nhưng không phải repo git - bỏ qua, xoá thư mục này rồi chạy lại nếu muốn tải lại"; return $false }
    Info "tải $($Repo.Url) (commit $($Repo.Commit.Substring(0, 7)))"
    if (-not (Invoke-Native "git" @("clone", "--filter=blob:none", "--no-checkout", $Repo.Url, $Dir))) {
        Warn "không tải được $($Repo.Url) - kiểm tra mạng rồi chạy lại"; return $false
    }
    if (-not (Invoke-Native "git" @("-c", "advice.detachedHead=false", "-C", $Dir, "checkout", "--quiet", $Repo.Commit))) {
        Warn "không chuyển được $($Repo.Name) về commit $($Repo.Commit)"; return $false
    }
    return $true
}

function Install-NodeProject([string]$Dir, [string]$Label) {
    if (Test-Path (Join-Path $Dir "node_modules")) { Ok "$Label`: đã cài thư viện Node"; return }
    if (Invoke-Native "npm" @("ci", "--no-audit", "--no-fund") $Dir) { Ok "$Label`: đã cài thư viện Node" }
    else { Warn "$Label`: npm ci lỗi - xem thông báo phía trên, chạy lại cai-dat.cmd" }
}

function Set-TomlLine([string]$Text, [string]$Key, [string]$Line) {
    # thay dòng "<key> = ..." đầu tiên (giữ nguyên kiểu xuống dòng của file)
    $re = New-Object System.Text.RegularExpressions.Regex ('(?m)^' + [regex]::Escape($Key) + '\s*=[^\r\n]*')
    return $re.Replace($Text, $Line.Replace('$', '$$'), 1)
}

# config.toml của MoneyPrinterTurbo: tạo từ config.example.toml (LLM Gemini, Edge TTS chờ lâu hơn, font có dấu tiếng
# Việt), rồi mỗi lần chạy chép key Gemini/Pexels mới nhất từ .env sang. Web của MoneyPrinterTurbo ghi đè file này
# khi bấm lưu (mất chú thích) — không sao, các dòng key vẫn tìm được.
function Sync-MptConfig([string]$Mpt, $envs) {
    $cfg = Join-Path $Mpt "config.toml"
    $example = Join-Path $Mpt "config.example.toml"
    if (Test-Path $cfg) {
        $text = [IO.File]::ReadAllText($cfg)
    } elseif (Test-Path $example) {
        $text = [IO.File]::ReadAllText($example)
        $text = Set-TomlLine $text "llm_provider" 'llm_provider = "gemini"'
        $text = Set-TomlLine $text "gemini_model_name" 'gemini_model_name = "gemini-flash-latest"'
        $text = Set-TomlLine $text "edge_tts_timeout" 'edge_tts_timeout = 120'
        $headers = [regex]::Matches($text, '(?m)^\[[^\]\r\n]+\]')
        if ($headers.Count -and $headers[$headers.Count - 1].Value -eq "[ui]") {
            # bảng [ui] nằm cuối file: thêm thiết lập cho web của MoneyPrinterTurbo (font mặc định thiếu dấu tiếng Việt)
            $text = $text.TrimEnd() + "`r`nlanguage = `"vi`"`r`nfont_name = `"BeVietnamPro-Bold.ttf`"`r`n" +
                    "voice_name = `"vi-VN-HoaiMyNeural-Female`"`r`n"
        }
        Ok "tạo config.toml cho MoneyPrinterTurbo"
    } else {
        Warn "không thấy config.example.toml trong $Mpt"; return
    }
    if ($envs["GEMINI_API_KEY"]) { $text = Set-TomlLine $text "gemini_api_key" ('gemini_api_key = "' + $envs["GEMINI_API_KEY"] + '"') }
    if ($envs["PEXELS_API_KEY"]) { $text = Set-TomlLine $text "pexels_api_keys" ('pexels_api_keys = ["' + $envs["PEXELS_API_KEY"] + '"]') }
    [IO.File]::WriteAllText($cfg, $text, (New-Object Text.UTF8Encoding $false))
    if ($envs["GEMINI_API_KEY"] -or $envs["PEXELS_API_KEY"]) { Ok "đã chép key từ .env sang $cfg" }
}

function Show-Status {
    Step "Tình trạng"
    if (-not (Test-Path ".venv\pyvenv.cfg")) { Warn "chưa có .venv - chạy cai-dat.cmd"; return }
    & (Join-Path $Root "vf-python.cmd") -m factory.status | Out-Host
}

Write-Host "Video Factory - cài đặt ($Root)" -ForegroundColor White
if ($KiemTra) { Show-Status; exit 0 }
if ($Root -match '\s' -or $Root -match '[^\x00-\x7F]') {
    Warn "đường dẫn có dấu cách hoặc ký tự có dấu: $Root - nên chuyển thư mục về chỗ như C:\video-factory để FFmpeg/Node không vấp"
}

# 1. Phần mềm nền ------------------------------------------------------------------------------------------------
Step "1/6 Kiểm tra phần mềm nền"
$missing = @()
$need = [ordered]@{
    git = "winget install --id Git.Git -e"
    uv = "winget install --id astral-sh.uv -e"
    node = "winget install --id OpenJS.NodeJS.LTS -e"
    npm = "winget install --id OpenJS.NodeJS.LTS -e"
    ffmpeg = "winget install --id Gyan.FFmpeg -e"
    ffprobe = "winget install --id Gyan.FFmpeg -e"
}
foreach ($tool in $need.Keys) {
    $path = Find-Tool $tool
    if ($path) { Ok "$tool  ($path)" } else { $missing += $need[$tool]; Write-Host "  [--] thiếu $tool" -ForegroundColor Red }
}
$nodeVer = $null
if (Find-Tool "node") {
    $nodeVer = (& node --version) -replace '^v', ''
    if ([int]($nodeVer.Split(".")[0]) -lt 22) {
        Write-Host "  [--] Node.js $nodeVer quá cũ (HyperFrames cần >= 22)" -ForegroundColor Red
        $missing += "winget upgrade --id OpenJS.NodeJS.LTS -e"
    }
}
$envs = Read-DotEnv
$chrome = Find-Chrome $envs
if ($chrome) { Ok "Chrome  ($chrome)" } else { Warn "không thấy Google Chrome (HyperFrames, Remotion, AI-auto cần): winget install --id Google.Chrome -e" }
if ($missing.Count) {
    Write-Host ""
    Write-Host "Thiếu phần mềm. Mở PowerShell rồi chạy các lệnh sau, xong ĐÓNG cửa sổ, mở lại và chạy lại cai-dat.cmd:" -ForegroundColor Yellow
    $missing | Select-Object -Unique | ForEach-Object { Write-Host "    $_" -ForegroundColor White }
    exit 1
}

# 2. File key .env ------------------------------------------------------------------------------------------------
Step "2/6 File key (.env)"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Ok "đã tạo .env từ .env.example - mở bằng Notepad để điền GEMINI_API_KEY và PEXELS_API_KEY (xem README)"
    Start-Process notepad.exe -ArgumentList ('"' + (Join-Path $Root ".env") + '"')
} else {
    Ok ".env đã có"
}
$envs = Read-DotEnv
foreach ($k in @("GEMINI_API_KEY", "PEXELS_API_KEY")) {
    if (-not $envs[$k]) { Info "chưa điền $k trong .env - điền xong thì chạy lại cai-dat.cmd để chép key sang MoneyPrinterTurbo" }
}

# 3. Web + project Node trong repo ----------------------------------------------------------------------------------
Step "3/6 Thư viện của web (Python) và các project Node trong repo"
if (Invoke-Native "uv" @("sync", "--frozen")) { Ok "thư viện Python của web (.venv)" }
else { Warn "uv sync lỗi ở thư mục gốc - xem thông báo phía trên" }
Install-NodeProject (Join-Path $Root "engines\hyperframes-academic") "HyperFrames"
Install-NodeProject (Join-Path $Root "engines\remotion-academic") "Remotion"
Install-NodeProject (Join-Path $Root "tools\elk") "ELK (dàn sơ đồ)"

# 4. Ba repo engine -------------------------------------------------------------------------------------------------
Step "4/6 Tải và cài 3 repo engine"
# MoneyPrinterTurbo: MPT_DIR trong .env → engines\MoneyPrinterTurbo → thư mục nằm cạnh repo này (giống factory/config.py)
$mpt = Join-Path $Root "engines\MoneyPrinterTurbo"
$beside = Join-Path (Split-Path -Parent $Root) "MoneyPrinterTurbo"
if ($envs["MPT_DIR"]) { $mpt = $envs["MPT_DIR"] }
elseif (-not (Test-Path $mpt) -and (Test-Path (Join-Path $beside "cli.py"))) { $mpt = $beside }
if (Get-Repo $Repos[0] $mpt) {
    if (Invoke-Native "uv" @("sync", "--frozen") $mpt) { Ok "MoneyPrinterTurbo: đã cài thư viện" }
    else { Warn "MoneyPrinterTurbo: uv sync lỗi" }
    Sync-MptConfig $mpt $envs
}

$aiauto = Join-Path $Root "engines\ai-auto-generate-video"
if (Get-Repo $Repos[1] $aiauto) { Install-NodeProject $aiauto "AI-auto-generate-video" }

$pixelle = Join-Path $Root "engines\pixelle-video"
if (Get-Repo $Repos[2] $pixelle) {
    # --no-install-project: engine tự trỏ PYTHONPATH vào repo nên không cần build gói pixelle-video.
    $synced = Invoke-Native "uv" @("sync", "--frozen", "--no-install-project", "--python", "3.12") $pixelle
    if (-not $synced) {
        # Smart App Control chặn Python tạm uv dùng để build moviepy 1.0.3 (chỉ có mã nguồn) → build ngay trong .venv
        Info "thử lại: build moviepy ngay trong .venv (máy bật Smart App Control hay gặp lỗi ở bước này)"
        $synced = Invoke-Native "uv" @("sync", "--frozen", "--no-install-project", "--python", "3.12",
                                       "--no-build-isolation-package", "moviepy") $pixelle
    }
    if ($synced) {
        Ok "Pixelle-Video: đã cài thư viện"
        # Pixelle chụp khung hình HTML bằng Chromium của Playwright
        if (Invoke-VenvPython (Join-Path $pixelle ".venv") @("-m", "playwright", "install", "--only-shell", "chromium") $pixelle) {
            Ok "Pixelle-Video: đã có Chromium cho Playwright"
        } else { Warn "Pixelle-Video: chưa tải được Chromium cho Playwright" }
    } else { Warn "Pixelle-Video: uv sync lỗi" }
}

# 5. Key ------------------------------------------------------------------------------------------------------------
Step "5/6 Kiểm tra key"
$envs = Read-DotEnv
if ($envs["GEMINI_API_KEY"]) { Ok "GEMINI_API_KEY" } else { Warn "chưa có GEMINI_API_KEY trong .env (viết nháp, đặt từ khoá ảnh)" }
if ($envs["PEXELS_API_KEY"]) { Ok "PEXELS_API_KEY" } else { Warn "chưa có PEXELS_API_KEY trong .env (ảnh và clip stock)" }

# 6. Tình trạng ------------------------------------------------------------------------------------------------------
Show-Status
Write-Host ""
if ($script:Problems.Count) {
    Write-Host "Còn $($script:Problems.Count) việc cần xử lý:" -ForegroundColor Yellow
    $script:Problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
    Write-Host "Xử lý xong thì chạy lại cai-dat.cmd (phần đã xong sẽ được bỏ qua)." -ForegroundColor Yellow
} else {
    Write-Host "Cài xong. Bấm đúp chay-web.cmd để mở web: http://127.0.0.1:8600" -ForegroundColor Green
    Write-Host "Muốn tự vẽ ảnh bằng GPU của máy: bấm đúp cai-comfyui.cmd (tải ~9 GB)." -ForegroundColor Green
}
