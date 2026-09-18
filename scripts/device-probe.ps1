param([string]$Adb='adb',[string]$Serial=$env:ANDROID_SERIAL,[string]$Request='{"command":"status"}',[string]$Out)
$ErrorActionPreference='Stop'
$selection=@(); if($Serial){$selection=@('-s',$Serial)}
$port=(& $Adb @selection forward tcp:0 localabstract:com.vertex.ghost.control.v1).Trim()
if($LASTEXITCODE -ne 0){throw 'ADB forward failed'}
$client=[System.Net.Sockets.TcpClient]::new()
try {
    $client.Connect('127.0.0.1',[int]$port)
    $stream=$client.GetStream();$stream.ReadTimeout=20000
    $bytes=[Text.Encoding]::UTF8.GetBytes($Request+"`n");$stream.Write($bytes,0,$bytes.Length)
    $line=[System.IO.MemoryStream]::new()
    while(($b=$stream.ReadByte()) -ge 0 -and $b -ne 10){$line.WriteByte([byte]$b)}
    $json=[Text.Encoding]::UTF8.GetString($line.ToArray());$result=$json|ConvertFrom-Json
    if($result.ok -and $result.byteLength){
        if(-not $Out){throw 'Image response requires -Out'}
        $dest=[IO.File]::Create([IO.Path]::GetFullPath($Out))
        try{$left=[int64]$result.byteLength;$buffer=[byte[]]::new(65536)
            while($left -gt 0){$n=$stream.Read($buffer,0,[int][Math]::Min($left,$buffer.Length));if($n -le 0){throw 'Truncated image'};$dest.Write($buffer,0,$n);$left-=$n}
        }finally{$dest.Dispose()}
    }
    $json
}finally{$client.Dispose();& $Adb @selection forward --remove "tcp:$port"}
