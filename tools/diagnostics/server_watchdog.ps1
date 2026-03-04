param(
    [string]$ServerArgs = "server.py --dxgi",
    [string]$OutLog = "watchdog_server.out.log",
    [string]$ErrLog = "watchdog_server.err.log",
    [string]$ChildPidFile = ".watchdog_server_child.pid",
    [int]$RestartDelaySec = 2
)

$ErrorActionPreference = "Continue"

while ($true) {
    try {
        $proc = Start-Process -FilePath python -ArgumentList $ServerArgs -WorkingDirectory (Get-Location).Path -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru
        Set-Content -Path $ChildPidFile -Value $proc.Id -Encoding ascii
        Wait-Process -Id $proc.Id
    } catch {
    }
    Start-Sleep -Seconds ([Math]::Max(1, $RestartDelaySec))
}
