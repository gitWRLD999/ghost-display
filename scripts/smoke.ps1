[CmdletBinding()]
param([string]$Adb='adb',[string]$Serial=$env:ANDROID_SERIAL,[string]$Evidence='ghost-test-results')
$ErrorActionPreference='Stop'
$selection=@();if($Serial){$selection=@('-s',$Serial)}
New-Item -ItemType Directory -Force $Evidence | Out-Null
$results=[System.Collections.Generic.List[object]]::new()
function Assert-Ghost($Condition,[string]$Name,$Detail){
    $results.Add(@{test=$Name;passed=[bool]$Condition;detail=$Detail})
    $results | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $Evidence 'smoke-results.json')
    if(-not $Condition){throw "FAILED: $Name ($Detail)"}
    Write-Host "PASS $Name"
}
function Quote-Android([string]$Value){return "'"+$Value.Replace("'","'\''")+"'"}
function Ghost([string[]]$Words){
    $cmd='sh /data/local/tmp/ghostctl '+(($Words|ForEach-Object{Quote-Android $_})-join ' ')
    $raw=(& $Adb @selection shell $cmd)-join "`n"
    if($LASTEXITCODE -ne 0){throw $raw}
    $j=$raw|ConvertFrom-Json;if(-not $j.ok){throw $raw};return $j
}
function Fixture([int]$Display){
    $raw=(& $Adb @selection shell run-as com.vertex.ghost cat "files/test-display-$Display.json")-join "`n"
    return $raw|ConvertFrom-Json
}
function Capture([string]$Name){
    $null=Ghost @('screenshot','--out','/data/local/tmp/ghost-smoke.png')
    $path=Join-Path $Evidence $Name
    & $Adb @selection pull /data/local/tmp/ghost-smoke.png $path | Out-Null
    $bytes=[IO.File]::ReadAllBytes([IO.Path]::GetFullPath($path))
    if($bytes.Length -lt 1000 -or $bytes[0] -ne 137 -or $bytes[1] -ne 80){throw 'Invalid PNG'}
    return $path
}
# This test starts a fresh Ghost session and opens a dedicated physical test activity.
$keyguard=(& $Adb @selection shell dumpsys window policy)-join "`n"
if($keyguard -match '(?m)^\s+showing=true\s*$'){throw 'Unlock the phone before the dual-display smoke test.'}
$null=Ghost @('stop')
$first=Ghost @('start');$second=Ghost @('start');$display=[int]$first.displayId
Assert-Ghost ($display -gt 0 -and $display -eq $second.displayId) 'idempotent-start' $display
& $Adb @selection shell am start --user 0 --display 0 -f 0x18000000 -n com.vertex.ghost/.GhostTestActivity | Out-Null
Start-Sleep -Milliseconds 600
& $Adb @selection shell input -d 0 text PHYSICAL | Out-Null
$null=Ghost @('open-url','https://example.com')
Start-Sleep -Seconds 3
$null=Capture 'chrome.png'
$null=Ghost @('tap','600','134')
$null=Ghost @('text','https://example.com')
$null=Ghost @('key','ENTER')
$windows=(& $Adb @selection shell dumpsys window)-join "`n"
$inputDump=(& $Adb @selection shell dumpsys input)-join "`n"
$windows | Set-Content (Join-Path $Evidence 'focus-window.txt')
$inputDump | Set-Content (Join-Path $Evidence 'focus-input.txt')
Assert-Ghost ($windows -match 'mTopFocusedDisplayId=0' -and $inputDump -match 'FocusedDisplayId: 0') 'physical-focus-retained' 'WindowManager + InputDispatcher'
$physical=Fixture 0
Assert-Ghost ($physical.text -eq 'PHYSICAL') 'physical-text-unchanged' $physical.text
$null=Ghost @('open-component','com.vertex.ghost/.GhostTestActivity')
Start-Sleep -Milliseconds 800
$before=Capture 'before-actions.png'
$null=Ghost @('text','Ghost input works')
$null=Ghost @('tap','600','374')
$null=Ghost @('long-press','600','374','750')
$null=Ghost @('swipe','600','1500','600','700','450')
Start-Sleep -Milliseconds 800
$fixture=Fixture $display
Assert-Ghost ($fixture.text -eq 'Ghost input works' -and $fixture.clicks -eq 1 -and $fixture.longPresses -eq 1 -and $fixture.scrollY -gt 0) 'targeted-text-tap-longpress-swipe' $fixture
$after=Capture 'after-actions.png'
Assert-Ghost ((Get-FileHash $before).Hash -ne (Get-FileHash $after).Hash) 'capture-changed-after-input' 'valid PNG before/after + fixture state'
$null=Ghost @('key','DEL')
Assert-Ghost ((Fixture $display).text -eq 'Ghost input work') 'targeted-key' 'DEL affected Ghost only'
Assert-Ghost ((Fixture 0).text -eq 'PHYSICAL') 'dual-display-input-isolated' 'PHYSICAL retained'
$times=@()
for($n=0;$n -lt 12;$n++){$watch=[Diagnostics.Stopwatch]::StartNew();$null=Ghost @('screenshot','--out','/data/local/tmp/ghost-benchmark.jpg','--format','jpeg','--quality','75','--max-width','800');$watch.Stop();$times+=$watch.ElapsedMilliseconds}
Assert-Ghost ($times.Count -eq 12) 'repeated-capture' @{captures=12;meanMs=($times|Measure-Object -Average).Average;maxMs=($times|Measure-Object -Maximum).Maximum}
$state=Ghost @('status')
$state | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $Evidence 'status.json')
Assert-Ghost ($state.captureHealth -eq 'ready' -and $state.inputHealth -eq 'ok') 'reported-health' $state
Write-Host "Evidence: $Evidence. Ghost remains running on display $display for viewer/lock tests."
