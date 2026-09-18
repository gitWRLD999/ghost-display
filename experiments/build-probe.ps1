[CmdletBinding()]
param([string]$JavaHome=$env:JAVA_HOME,[string]$AndroidSdk=$env:ANDROID_HOME,
  [ValidateSet('GhostDisplayExperiment','GhostBrowserDemo')][string]$SourceName='GhostDisplayExperiment')
$ErrorActionPreference='Stop'
if(-not $JavaHome -or -not $AndroidSdk){throw 'Pass -JavaHome and -AndroidSdk, or set JAVA_HOME and ANDROID_HOME.'}
$outputDirectory=Join-Path $PSScriptRoot ('build/'+$SourceName)
New-Item -ItemType Directory -Force $outputDirectory | Out-Null
$androidJar=Join-Path $AndroidSdk 'platforms/android-36/android.jar'
$javac=Join-Path $JavaHome 'bin/javac.exe'
& $javac -source 17 -target 17 -classpath $androidJar -d $outputDirectory (Join-Path $PSScriptRoot ($SourceName+'.java'))
if($LASTEXITCODE){throw 'Probe compilation failed'}
$oldJava=$env:JAVA_HOME
try {
  $env:JAVA_HOME=$JavaHome
  $classes=@(Get-ChildItem -LiteralPath $outputDirectory -Filter '*.class' | ForEach-Object FullName)
  & (Join-Path $AndroidSdk 'build-tools/36.0.0/d8.bat') --lib $androidJar --min-api 34 --output $outputDirectory @classes
  if($LASTEXITCODE){throw 'Probe dex generation failed'}
}finally{$env:JAVA_HOME=$oldJava}
Write-Output (Join-Path $outputDirectory 'classes.dex')
