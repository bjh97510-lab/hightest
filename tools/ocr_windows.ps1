param([string]$InDir, [string]$OutDir)
# Windows 내장 OCR(한국어)로 폴더의 jpg/png 사진마다 줄 단위 텍스트·좌표를 JSON으로 저장 (이미 있으면 건너뜀)
# 사용법: powershell -ExecutionPolicy Bypass -File tools/ocr_windows.ps1 -InDir <사진 폴더> -OutDir <출력 폴더>
# 필요: Windows 10/11 + 한국어 OCR 언어팩
Add-Type -AssemblyName System.Runtime.WindowsRuntime
# WinRT 형식 리터럴은 스크립트 구문 분석 시점에 풀리지 않으므로, 형식을 불러온 뒤 본문을 문자열로 실행한다
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
# 확장 메서드 형식은 형식 리터럴로 찾지 못하는 경우가 있어 불러온 어셈블리에서 직접 꺼냄
$ext = ([System.AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GetName().Name -eq 'System.Runtime.WindowsRuntime' }).GetType('System.WindowsRuntimeSystemExtensions')

Invoke-Expression @'
$asTask = ($ext.GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait() | Out-Null; $task.Result }

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('ko'))
if (-not $engine) { throw '한국어 OCR 엔진을 만들 수 없습니다. 설정 > 시간 및 언어에서 한국어 언어팩을 설치하세요.' }
New-Item -ItemType Directory -Force $OutDir | Out-Null
foreach ($f in Get-ChildItem $InDir -File | Where-Object { $_.Extension -match '^\.(jpe?g|png)$' } | Sort-Object Name) {
  $dest = Join-Path $OutDir ($f.BaseName + '.json')
  if (Test-Path $dest) { continue }
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($f.FullName)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
  if ($null -eq $res) { $stream.Dispose(); throw "OCR 실패: $($f.Name)" }
  $lines = foreach ($l in $res.Lines) {
    $ws = @($l.Words)
    $box = @([int]($ws | ForEach-Object { $_.BoundingRect.X } | Measure-Object -Minimum).Minimum,
             [int]($ws | ForEach-Object { $_.BoundingRect.Y } | Measure-Object -Minimum).Minimum,
             [int]($ws | ForEach-Object { $_.BoundingRect.X + $_.BoundingRect.Width } | Measure-Object -Maximum).Maximum,
             [int]($ws | ForEach-Object { $_.BoundingRect.Y + $_.BoundingRect.Height } | Measure-Object -Maximum).Maximum)
    [pscustomobject]@{ text = $l.Text; box = $box
      words = @($ws | ForEach-Object { [pscustomobject]@{ t = $_.Text; b = @([int]$_.BoundingRect.X, [int]$_.BoundingRect.Y, [int]($_.BoundingRect.X + $_.BoundingRect.Width), [int]($_.BoundingRect.Y + $_.BoundingRect.Height)) } }) }
  }
  $out = [pscustomobject]@{ file = $f.Name; w = $bmp.PixelWidth; h = $bmp.PixelHeight; angle = $res.TextAngle; lines = @($lines) }
  [System.IO.File]::WriteAllText($dest, ($out | ConvertTo-Json -Depth 6 -Compress), [System.Text.UTF8Encoding]::new($false))
  $stream.Dispose()
  Write-Output ("{0} lines={1}" -f $f.Name, @($res.Lines).Count)
}
'@
