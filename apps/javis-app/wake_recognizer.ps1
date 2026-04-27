Add-Type -AssemblyName System.Speech

$culture = $null
try {
  $culture = [System.Globalization.CultureInfo]::GetCultureInfo("ko-KR")
  $recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine($culture)
} catch {
  $recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine
}

$phrases = @(
  "헤이 일어나",
  "헤이 자비스",
  "자비스 일어나",
  "헤이 재비스",
  "일어나 자비스"
)

$choices = New-Object System.Speech.Recognition.Choices
$choices.Add($phrases)

$grammarBuilder = New-Object System.Speech.Recognition.GrammarBuilder
if ($culture -ne $null) {
  $grammarBuilder.Culture = $culture
}
$grammarBuilder.Append($choices)

$grammar = New-Object System.Speech.Recognition.Grammar($grammarBuilder)
$recognizer.LoadGrammar($grammar)
$recognizer.SetInputToDefaultAudioDevice()

Register-ObjectEvent -InputObject $recognizer -EventName SpeechRecognized -Action {
  $result = $Event.SourceEventArgs.Result
  if ($null -eq $result) {
    return
  }

  $text = ($result.Text -replace "`r|`n", " ").Trim()
  $confidence = [Math]::Round($result.Confidence, 3)
  [Console]::Out.WriteLine("HEARD::{0}::{1}" -f $text, $confidence)
} | Out-Null

[Console]::Out.WriteLine("READY")
$recognizer.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)

try {
  while ($true) {
    Wait-Event -Timeout 1 | Out-Null
  }
} finally {
  $recognizer.RecognizeAsyncStop()
  Get-EventSubscriber | Unregister-Event
}
