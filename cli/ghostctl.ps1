[CmdletBinding(PositionalBinding=$false)]
param(
    [string]$Serial = $env:ANDROID_SERIAL,
    [string]$Adb = 'adb',
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$CommandArgs
)
$ErrorActionPreference = 'Stop'
function Quote-Android([string]$Value) { return "'" + $Value.Replace("'", "'\''") + "'" }
$adbArgs = @()
if ($Serial) { $adbArgs += @('-s', $Serial) }
$localOut = $null
$argsList = [System.Collections.Generic.List[string]]::new()
foreach ($arg in $CommandArgs) { $argsList.Add($arg) }
if ($argsList.Count -gt 0 -and $argsList[0] -eq 'screenshot') {
    $outIndex = $argsList.IndexOf('--out')
    if ($outIndex -ge 0) {
        if ($outIndex + 1 -ge $argsList.Count) { throw '--out requires a PC path.' }
        $localOut = [System.IO.Path]::GetFullPath($argsList[$outIndex + 1])
        $argsList.RemoveAt($outIndex + 1)
        $argsList.RemoveAt($outIndex)
    }
}
$remote = 'sh /data/local/tmp/ghostctl ' + (($argsList | ForEach-Object { Quote-Android $_ }) -join ' ')
# Process streams preserve binary PNG bytes on every supported PowerShell version.
$psi = [System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $Adb
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true
foreach ($arg in ($adbArgs + @('exec-out', $remote))) { $psi.ArgumentList.Add($arg) }
$p = [System.Diagnostics.Process]::Start($psi)
$errorRead = $p.StandardError.ReadToEndAsync()
$tempOut = if ($localOut) { $localOut + '.part-' + [guid]::NewGuid().ToString('N') } else { $null }
$dest = if ($localOut) { [System.IO.File]::Create($tempOut) } else { [Console]::OpenStandardOutput() }
try { $p.StandardOutput.BaseStream.CopyTo($dest) } finally { if ($localOut) { $dest.Dispose() } }
$p.WaitForExit()
$errorText = $errorRead.GetAwaiter().GetResult()
if ($errorText) { [Console]::Error.Write($errorText) }
if ($p.ExitCode -ne 0) {
    if ($tempOut) { Remove-Item -LiteralPath $tempOut -ErrorAction SilentlyContinue }
    throw "ghostctl failed (exit $($p.ExitCode))."
}
if ($localOut) {
    $bytes = [IO.File]::ReadAllBytes($tempOut)
    $png = $bytes.Length -ge 8 -and $bytes[0] -eq 137 -and $bytes[1] -eq 80 -and $bytes[2] -eq 78 -and $bytes[3] -eq 71
    $jpeg = $bytes.Length -ge 3 -and $bytes[0] -eq 255 -and $bytes[1] -eq 216 -and $bytes[2] -eq 255
    if (-not ($png -or $jpeg)) {
        Remove-Item -LiteralPath $tempOut
        throw ('Screenshot failed: ' + [Text.Encoding]::UTF8.GetString($bytes))
    }
    Move-Item -LiteralPath $tempOut -Destination $localOut -Force
    @{ok=$true; path=$localOut; bytes=$bytes.Length} | ConvertTo-Json -Compress
}
