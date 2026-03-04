param(
    [string]$ServerArgs = "server.py --dxgi",
    [string]$OutLog = "watchdog_server.out.log",
    [string]$ErrLog = "watchdog_server.err.log",
    [string]$ChildPidFile = "watchdog_server_child.pid",
    [int]$RestartDelaySec = 2,
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
$pidsDir = Join-Path $ArtifactsDir "pids"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
New-Item -ItemType Directory -Path $pidsDir -Force | Out-Null

if (-not [IO.Path]::IsPathRooted($OutLog)) { $OutLog = Join-Path $logsDir $OutLog }
if (-not [IO.Path]::IsPathRooted($ErrLog)) { $ErrLog = Join-Path $logsDir $ErrLog }
if (-not [IO.Path]::IsPathRooted($ChildPidFile)) { $ChildPidFile = Join-Path $pidsDir $ChildPidFile }

while ($true) {
    try {
        $proc = Start-Process -FilePath python -ArgumentList $ServerArgs -WorkingDirectory (Get-Location).Path -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru
        Set-Content -Path $ChildPidFile -Value $proc.Id -Encoding ascii
        Wait-Process -Id $proc.Id
    } catch {
    }
    Start-Sleep -Seconds ([Math]::Max(1, $RestartDelaySec))
}
