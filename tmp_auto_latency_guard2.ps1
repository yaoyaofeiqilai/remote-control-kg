$ErrorActionPreference='Stop'
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$sampleFile = "auto_samples_audio_guard2_$ts.jsonl"
$outLog = "tmp_latency_audio_guard2_$ts.out.log"
$errLog = "tmp_latency_audio_guard2_$ts.err.log"
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like '*server.py*--dxgi*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Milliseconds 400
$proc = Start-Process -FilePath python -ArgumentList 'server.py --dxgi' -WorkingDirectory (Get-Location).Path -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
$base='http://127.0.0.1:5000'
$ready=$false
for($i=0;$i -lt 25;$i++){
  try { $null = Invoke-RestMethod -Uri "$base/api/info" -TimeoutSec 1; $ready=$true; break } catch { Start-Sleep -Milliseconds 400 }
}
if(-not $ready){ throw 'server_not_ready' }
$rows = New-Object System.Collections.Generic.List[string]
for($i=0;$i -lt 100;$i++){
  $now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  try {
    $vh = Invoke-RestMethod -Uri "$base/api/video_health" -TimeoutSec 1
    $client = $vh.client_stats
    $track = $vh.track_stats
    $audioCap = $null
    if(($i % 10) -eq 0){
      try { $audioCap = [bool](Invoke-RestMethod -Uri "$base/api/audio_health" -TimeoutSec 1).capture_running } catch { $audioCap = $null }
    }
    $obj = [ordered]@{
      t_ms = $now
      i = $i
      client_up = [bool]$vh.client_up
      bitrate_kbps = [double]($vh.bitrate_kbps)
      runtime_bitrate_scale = [double]($vh.runtime_bitrate_scale)
      capture_fps = [double]($vh.capture_fps)
      recv_fps = [double]($track.recv_fps)
      ts_catchup = [double]($track.ts_catchup)
      playout_delay_ms = [double]($client.playout_delay_ms)
      playout_delay_ewma_ms = [double]($client.playout_delay_ewma_ms)
      decode_ms = [double]($client.decode_ms)
      jitter_ms = [double]($client.jitter_ms)
      frames_backlog = [double]($client.frames_backlog)
      playback_rate = [double]($client.playback_rate)
      audio_capture_running = $audioCap
    }
    $rows.Add(($obj | ConvertTo-Json -Compress))
  } catch {
    $rows.Add(([ordered]@{ t_ms=$now; i=$i; err='poll_failed'; msg=$_.Exception.Message } | ConvertTo-Json -Compress))
  }
  Start-Sleep -Seconds 1
}
$rows | Set-Content -Path $sampleFile -Encoding UTF8
$parsed = $rows | ForEach-Object { try { $_ | ConvertFrom-Json } catch { $null } } | Where-Object { $_ }
$online = $parsed | Where-Object { $_.client_up -eq $true -and [double]$_.playout_delay_ms -gt 0 }
$connected = $parsed | Where-Object { $_.client_up -eq $true }
if($online.Count -gt 0){
  $vals = $online | ForEach-Object { [double]$_.playout_delay_ms }
  $sorted = $vals | Sort-Object
  $avg = [math]::Round((($vals | Measure-Object -Average).Average),2)
  $max = [math]::Round((($vals | Measure-Object -Maximum).Maximum),2)
  $end = [math]::Round($vals[-1],2)
  $p90 = [math]::Round($sorted[[int][math]::Floor(($sorted.Count-1)*0.9)],2)
  $tail = @(); if($vals.Count -gt 20){ $tail = $vals[($vals.Count-20)..($vals.Count-1)] } else { $tail = $vals }
  $tailAvg = [math]::Round((($tail | Measure-Object -Average).Average),2)
  $audioStates = $parsed | Where-Object { $_.audio_capture_running -ne $null } | ForEach-Object { $_.audio_capture_running }
  $audioOnTicks = ($audioStates | Where-Object { $_ -eq $true }).Count
  Write-Output "SAMPLE_FILE=$sampleFile"
  Write-Output "ONLINE_DELAY_SAMPLES=$($vals.Count)"
  Write-Output "CLIENT_UP_COUNT=$($connected.Count)"
  Write-Output "AUDIO_CAPTURE_TRUE_TICKS=$audioOnTicks"
  Write-Output "AVG_DELAY_MS=$avg"
  Write-Output "TAIL20_AVG_MS=$tailAvg"
  Write-Output "P90_DELAY_MS=$p90"
  Write-Output "MAX_DELAY_MS=$max"
  Write-Output "END_DELAY_MS=$end"
} else {
  Write-Output "SAMPLE_FILE=$sampleFile"
  Write-Output "NO_ONLINE_DELAY_SAMPLES"
  Write-Output "CLIENT_UP_COUNT=$($connected.Count)"
}
if($proc -and -not $proc.HasExited){ Stop-Process -Id $proc.Id -Force }
