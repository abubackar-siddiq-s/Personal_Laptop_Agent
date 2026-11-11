param([string]$ImagePath)

$ErrorActionPreference = "Stop"

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { 
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' 
    })[0]

    Function Await-WinRt($WinRtTask, $ResultType) {
        $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
        $netTask = $asTask.Invoke($null, @($WinRtTask))
        $netTask.Wait(-1) | Out-Null
        return $netTask.Result
    }

    [Windows.Media.Ocr.OcrEngine, Windows.Foundation.Diagnostics, ContentType = WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation.Diagnostics, ContentType = WindowsRuntime] | Out-Null
    [Windows.Storage.StorageFile, Windows.Foundation.Diagnostics, ContentType = WindowsRuntime] | Out-Null

    if (-not $ImagePath -or -not (Test-Path $ImagePath)) {
        $errJson = @{
            success = $false
            error = "Image file path not provided or does not exist: $ImagePath"
        } | ConvertTo-Json -Compress
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        Write-Output $errJson
        exit 0
    }

    $fullPath = [System.IO.Path]::GetFullPath($ImagePath)
    $file = Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($fullPath)) ([Windows.Storage.StorageFile])
    $stream = Await-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if (-not $engine) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("en-US"))
    }
    
    if (-not $engine) {
        $errJson = @{
            success = $false
            error = "Windows OCR engine could not be initialized for user profile languages or en-US."
        } | ConvertTo-Json -Compress
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        Write-Output $errJson
        exit 0
    }

    $ocrResult = Await-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    $linesList = @()
    foreach ($line in $ocrResult.Lines) {
        $wordsList = @()
        $minX = 999999
        $minY = 999999
        $maxX = 0
        $maxY = 0

        foreach ($word in $line.Words) {
            $wx = [int]$word.BoundingRect.X
            $wy = [int]$word.BoundingRect.Y
            $ww = [int]$word.BoundingRect.Width
            $wh = [int]$word.BoundingRect.Height

            if ($wx -lt $minX) { $minX = $wx }
            if ($wy -lt $minY) { $minY = $wy }
            if (($wx + $ww) -gt $maxX) { $maxX = $wx + $ww }
            if (($wy + $wh) -gt $maxY) { $maxY = $wy + $wh }

            $wordsList += @{
                text = $word.Text
                bbox = @{
                    x1 = $wx
                    y1 = $wy
                    x2 = $wx + $ww
                    y2 = $wy + $wh
                    width = $ww
                    height = $wh
                }
            }
        }

        if ($minX -eq 999999) { $minX = 0; $maxX = 0; $minY = 0; $maxY = 0 }

        $linesList += @{
            text = $line.Text
            bbox = @{
                x1 = $minX
                y1 = $minY
                x2 = $maxX
                y2 = $maxY
                width = [Math]::Max(0, $maxX - $minX)
                height = [Math]::Max(0, $maxY - $minY)
            }
            words = $wordsList
        }
    }

    $output = @{
        success = $true
        text = $ocrResult.Text
        line_count = $linesList.Count
        lines = $linesList
    }

    $json = $output | ConvertTo-Json -Depth 6 -Compress
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Write-Output $json
}
catch {
    $err = $_.Exception.Message
    $output = @{
        success = $false
        error = "WinRT OCR error: $err"
    } | ConvertTo-Json -Compress
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Write-Output $output
}

