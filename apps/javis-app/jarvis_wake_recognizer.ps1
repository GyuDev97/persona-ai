Add-Type -AssemblyName System.Speech

function New-HangulText {
  param(
    [Parameter(Mandatory = $true)]
    [int[]] $CodePoints
  )

  return (-join ($CodePoints | ForEach-Object { [char] $_ }))
}

$culture = $null
$recognizer = $null
$installedRecognizers = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()

if (-not $installedRecognizers -or $installedRecognizers.Count -eq 0) {
  [Console]::Out.WriteLine("ERROR::NO_RECOGNIZER::No Windows speech recognizer is installed.")
  exit 2
}

$koRecognizerInfo = $installedRecognizers | Where-Object { $_.Culture.Name -eq "ko-KR" } | Select-Object -First 1
if ($null -eq $koRecognizerInfo) {
  $availableCultures = ($installedRecognizers | ForEach-Object { $_.Culture.Name }) -join ", "
  [Console]::Out.WriteLine("ERROR::NO_KO_RECOGNIZER::Installed recognizers: {0}" -f $availableCultures)
  exit 3
}

try {
  $culture = $koRecognizerInfo.Culture
  $recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine($culture)
} catch {
  [Console]::Out.WriteLine("ERROR::ENGINE_INIT_FAILED::{0}" -f $_.Exception.Message)
  exit 4
}

$phrases = @(
  (New-HangulText -CodePoints @(0xD5E4, 0xC774, 0x20, 0xC77C, 0xC5B4, 0xB098)),
  (New-HangulText -CodePoints @(0xD5E4, 0xC774, 0x20, 0xC790, 0xBE44, 0xC2A4)),
  (New-HangulText -CodePoints @(0xC790, 0xBE44, 0xC2A4, 0x20, 0xC77C, 0xC5B4, 0xB098)),
  (New-HangulText -CodePoints @(0xD5E4, 0xC774, 0x20, 0xC7AC, 0xBE44, 0xC2A4)),
  (New-HangulText -CodePoints @(0xC77C, 0xC5B4, 0xB098, 0x20, 0xC790, 0xBE44, 0xC2A4))
)

$choices = New-Object System.Speech.Recognition.Choices
$choices.Add($phrases)

$grammarBuilder = New-Object System.Speech.Recognition.GrammarBuilder
if ($culture -ne $null) {
  $grammarBuilder.Culture = $culture
}
$grammarBuilder.Append($choices)

$grammar = New-Object System.Speech.Recognition.Grammar($grammarBuilder)
try {
  $recognizer.LoadGrammar($grammar)
} catch {
  [Console]::Out.WriteLine("ERROR::LOAD_GRAMMAR_FAILED::{0}" -f $_.Exception.Message)
  exit 5
}

try {
  $recognizer.SetInputToDefaultAudioDevice()
} catch {
  [Console]::Out.WriteLine("ERROR::AUDIO_DEVICE_FAILED::{0}" -f $_.Exception.Message)
  exit 6
}

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
try {
  $recognizer.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)
} catch {
  [Console]::Out.WriteLine("ERROR::RECOGNIZE_START_FAILED::{0}" -f $_.Exception.Message)
  exit 7
}

try {
  while ($true) {
    Wait-Event -Timeout 1 | Out-Null
  }
} finally {
  if ($null -ne $recognizer) {
    $recognizer.RecognizeAsyncStop()
  }
  Get-EventSubscriber | Unregister-Event
}
