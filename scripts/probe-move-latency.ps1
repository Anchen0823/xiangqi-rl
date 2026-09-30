# Measures what the renderer's request sequence costs. The renderer sends `stop`
# immediately before `playMove` so a speculative analysis cannot hold the move.
# Run with and without -Stop to compare. The engine is strictly serial, so the
# `playMove` wait below is the delay a user would feel as "my piece did not move".
param(
  [string]$Difficulty = 'club',
  [string]$Move = 'h2e2',
  [switch]$Stop,
  [int]$DelayMs = 0,
  [string]$Engine = 'build\native\xiangqi-engine.exe'
)

$exe = (Resolve-Path (Join-Path $PSScriptRoot "..\$Engine")).Path

$si = New-Object System.Diagnostics.ProcessStartInfo
$si.FileName = $exe
$si.RedirectStandardInput = $true
$si.RedirectStandardOutput = $true
$si.UseShellExecute = $false
$si.CreateNoWindow = $true
$p = [System.Diagnostics.Process]::Start($si)

function SendLine([string]$json) { $p.StandardInput.WriteLine($json); $p.StandardInput.Flush() }
function ReadUntil([string]$id, [System.Diagnostics.Stopwatch]$clock) {
  while (-not $p.StandardOutput.EndOfStream) {
    $line = $p.StandardOutput.ReadLine()
    if ($line -match ('"id":"' + $id + '"')) { return $clock.ElapsedMilliseconds }
  }
  return -1
}

$sw = [System.Diagnostics.Stopwatch]::StartNew()
SendLine '{"id":"boot","method":"newGame","params":{}}'
$null = ReadUntil 'boot' $sw

$sw.Restart()
SendLine ('{"id":"a","method":"analyze","params":{"difficulty":"' + $Difficulty + '"}}')
if ($Stop -and $DelayMs -gt 0) { [System.Threading.Thread]::Sleep($DelayMs) }
if ($Stop) { SendLine '{"id":"s","method":"stop","params":{}}' }
SendLine ('{"id":"m","method":"playMove","params":{"move":"' + $Move + '"}}')

$analyzeMs = ReadUntil 'a' $sw
$moveMs = ReadUntil 'm' $sw

SendLine '{"id":"q","method":"quit","params":{}}'
if (-not $p.WaitForExit(5000)) { $p.Kill() }

$label = if ($Stop) { "stop after ${DelayMs} ms" } else { 'without stop (before fix)' }
"{0,-26} analyze {1,5} ms | playMove applied at {2,5} ms (waited {3,5} ms)" -f $label, $analyzeMs, $moveMs, $moveMs
