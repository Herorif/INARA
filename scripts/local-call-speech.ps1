$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$taskRequest = [Console]::In.ReadToEnd() | ConvertFrom-Json
if ($taskRequest.text -isnot [string] -or $taskRequest.text.Length -eq 0 -or $taskRequest.text.Length -gt 1200) { throw 'Invalid speech request' }
$taskSynth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$taskStream = New-Object System.IO.MemoryStream
try {
    $taskFormat = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $taskSynth.SetOutputToAudioStream($taskStream, $taskFormat)
    $taskSynth.Speak($taskRequest.text)
    $taskPcm = $taskStream.ToArray()
    $taskOutput = [Console]::OpenStandardOutput()
    # Emit a minimal PCM WAV header; no speaker, file or microphone is opened.
    $taskWriter = New-Object System.IO.BinaryWriter($taskOutput)
    $taskWriter.Write([Text.Encoding]::ASCII.GetBytes('RIFF'))
    $taskWriter.Write([int](36 + $taskPcm.Length))
    $taskWriter.Write([Text.Encoding]::ASCII.GetBytes('WAVEfmt '))
    $taskWriter.Write([int]16)
    $taskWriter.Write([int16]1)
    $taskWriter.Write([int16]1)
    $taskWriter.Write([int]24000)
    $taskWriter.Write([int]48000)
    $taskWriter.Write([int16]2)
    $taskWriter.Write([int16]16)
    $taskWriter.Write([Text.Encoding]::ASCII.GetBytes('data'))
    $taskWriter.Write([int]$taskPcm.Length)
    $taskWriter.Write($taskPcm)
    $taskWriter.Flush()
} finally {
    $taskSynth.Dispose()
    $taskStream.Dispose()
}
