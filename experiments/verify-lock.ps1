[CmdletBinding()]
param(
  [Parameter(Mandatory)][int]$DisplayId,
  [Parameter(Mandatory)][string]$Serial,
  [string]$Adb='adb',
  [ValidateRange(300,480)][int]$DurationSeconds=330,
  [string]$EvidenceDirectory=(Join-Path $PSScriptRoot ('build/evidence-'+(Get-Date -Format 'yyyyMMdd-HHmmss')))
)
$ErrorActionPreference='Stop'
if($DisplayId -le 0){throw 'Only a verified virtual display ID is allowed.'}
function Phone([string]$Command){
  $result=& $Adb -s $Serial shell $Command
  if($LASTEXITCODE){throw "ADB command failed: $Command"}
  return $result -join "`n"
}
function Observe {
  $policy=Phone 'dumpsys window policy'
  $display=Phone 'dumpsys display'
  $panels=@([regex]::Matches($display,'(?m)^\s*DisplayDeviceInfo\{"Built-in Screen"[^\r\n]*?state (\w+), committedState (\w+)') | ForEach-Object {
    [ordered]@{state=$_.Groups[1].Value;committedState=$_.Groups[2].Value}
  })
  $fixture=(Phone "run-as com.vertex.ghost cat files/test-display-$DisplayId.json") | ConvertFrom-Json
  $entry=[ordered]@{
    elapsedSeconds=[Math]::Round($timer.Elapsed.TotalSeconds,2)
    locked=($policy -match '(?m)^\s+showing=true\s*$')
    physicalScreenOff=($policy -match 'screenState=SCREEN_STATE_OFF')
    panels=$panels
    fixture=$fixture
  }
  $samples.Add($entry)
  $samples | ConvertTo-Json -Depth 7 | Set-Content (Join-Path $EvidenceDirectory 'samples.json')
  Write-Host ($entry | ConvertTo-Json -Compress -Depth 6)
  if(-not $entry.locked -or -not $entry.physicalScreenOff){throw 'Lock/off condition changed; duration test invalid.'}
  if($panels.Count -lt 1 -or @($panels | Where-Object {$_.state -ne 'OFF' -or $_.committedState -ne 'OFF'}).Count){
    throw 'Physical panels are not confirmed OFF; inspect OEM diagnostics.'
  }
  if($fixture.displayId -ne $DisplayId){throw 'Fixture display mismatch.'}
  if($samples.Count -gt 1 -and $fixture.seconds -le $samples[$samples.Count-2].fixture.seconds){throw 'Fixture clock did not advance.'}
  return $fixture
}
New-Item -ItemType Directory -Force $EvidenceDirectory | Out-Null
$samples=[Collections.Generic.List[object]]::new()
$timer=[Diagnostics.Stopwatch]::StartNew()
# Start only after creating the probe, launching exactly one fixture, locking normally,
# and allowing the physical screen to settle. This script does not lock/wake the phone.
$null=Observe
while($timer.Elapsed.TotalSeconds -lt $DurationSeconds){
  Start-Sleep -Seconds ([Math]::Min(30,[Math]::Max(1,[Math]::Ceiling($DurationSeconds-$timer.Elapsed.TotalSeconds))))
  $null=Observe
}
$before=$samples[$samples.Count-1].fixture
$null=Phone "input -d $DisplayId tap 600 374"
$null=Phone "input -d $DisplayId text PASS-AFTER-LOCK"
Start-Sleep -Seconds 11
$after=Observe
if($after.clicks -ne ($before.clicks+1) -or $after.text -notlike '*PASS-AFTER-LOCK*'){throw 'Final targeted input failed.'}
& $Adb -s $Serial pull /data/local/tmp/ghost-experiment-vdm.png (Join-Path $EvidenceDirectory 'after.png')
if($LASTEXITCODE){throw 'Capture pull failed.'}
Write-Output 'Sampled lock/off and fixture/input assertions passed. Inspect after.png for actual rendered content; review power wake logs for interruptions between samples.'
