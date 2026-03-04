param(
    [string]$PidFile = 'live_server.pid',
    [string]$OutLog = 'live_tuned_server.out.log',
    [string]$ErrLog = 'live_tuned_server.err.log',
    [string]$ServerArgs = 'server.py --dxgi',
    [int]$ReadyWaitSec = 30,
    [string]$ArtifactsDir = ''
)

$ErrorActionPreference = 'Stop'
$startedAt = Get-Date

if ([string]::IsNullOrWhiteSpace($ArtifactsDir)) {
    $ArtifactsDir = $env:RC_ARTIFACTS_DIR
}
if ([string]::IsNullOrWhiteSpace($ArtifactsDir)) {
    $ArtifactsDir = 'artifacts'
}

$logsDir = Join-Path $ArtifactsDir 'logs'
$pidsDir = Join-Path $ArtifactsDir 'pids'
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
New-Item -ItemType Directory -Path $pidsDir -Force | Out-Null

if (-not [IO.Path]::IsPathRooted($PidFile)) { $PidFile = Join-Path $pidsDir $PidFile }
if (-not [IO.Path]::IsPathRooted($OutLog)) { $OutLog = Join-Path $logsDir $OutLog }
if (-not [IO.Path]::IsPathRooted($ErrLog)) { $ErrLog = Join-Path $logsDir $ErrLog }

if (Test-Path $PidFile) {
    try {
        $oldPid = [int](Get-Content $PidFile | Select-Object -First 1)
        if ($oldPid -gt 0) {
            Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        }
    } catch {
    }
}

$proc = Start-Process -FilePath python -ArgumentList $ServerArgs -WorkingDirectory (Get-Location).Path -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru
Set-Content -Path $PidFile -Value $proc.Id -Encoding ascii

$ready = $false
for ($i = 0; $i -lt $ReadyWaitSec; $i++) {
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/info' -TimeoutSec 1
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

$elapsedMs = [int]((Get-Date) - $startedAt).TotalMilliseconds

if (-not $ready) {
    Write-Output ("RESTART_NOT_READY pid={0} elapsed_ms={1}" -f $proc.Id, $elapsedMs)
    exit 1
}

Write-Output ("RESTART_READY pid={0} elapsed_ms={1}" -f $proc.Id, $elapsedMs)
