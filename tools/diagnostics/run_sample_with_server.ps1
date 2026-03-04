param(
    [int]$Duration = 100,
    [double]$TimeoutSec = 1.5,
    [string]$OutLog = "cycle_server.out.log",
    [string]$ErrLog = "cycle_server.err.log",
    [string]$ArtifactsDir = ''
)

$ErrorActionPreference = "Continue"

if ([string]::IsNullOrWhiteSpace($ArtifactsDir)) {
    $ArtifactsDir = $env:RC_ARTIFACTS_DIR
}
if ([string]::IsNullOrWhiteSpace($ArtifactsDir)) {
    $ArtifactsDir = "artifacts"
}

$logsDir = Join-Path $ArtifactsDir "logs"
$samplesDir = Join-Path $ArtifactsDir "samples"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
New-Item -ItemType Directory -Path $samplesDir -Force | Out-Null

if (-not [IO.Path]::IsPathRooted($OutLog)) { $OutLog = Join-Path $logsDir $OutLog }
if (-not [IO.Path]::IsPathRooted($ErrLog)) { $ErrLog = Join-Path $logsDir $ErrLog }

$sample = Join-Path $samplesDir ("auto_samples_live_tuned_cycle_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".jsonl")
$proc = Start-Process -FilePath python -ArgumentList "server.py --dxgi" -WorkingDirectory (Get-Location).Path -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru

try {
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/info" -TimeoutSec 1
            $ready = $true
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ready) {
        throw "server_not_ready"
    }
    python tools/diagnostics/sample_tablet_latency.py --duration $Duration --timeout $TimeoutSec --output $sample
} finally {
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}
