param([string]$PythonExecutable='python')
$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major -ne 7){throw 'PowerShell 7 required'}
$word=$null
$document=$null
$records=@{}
try {
 $word=New-Object -ComObject Word.Application
 $word.Visible=$false
 $word.DisplayAlerts=0
 foreach($language in @('en','zh')) {
  $inputPath=Join-Path $PSScriptRoot ('report-mic-'+$language+'_w5-candidate-r2.docx')
  $outputPath=[IO.Path]::ChangeExtension($inputPath,'pdf')
  $document=$word.Documents.Open($inputPath,$false,$false)
  if($document.TablesOfContents.Count -ne 1){throw 'Expected one contents field'}
  $document.TablesOfContents.Item(1).Update()
  $contents=$document.TablesOfContents.Item(1).Range
  $contents.ParagraphFormat.SpaceBefore=0
  $contents.ParagraphFormat.SpaceAfter=0
  $contents.ParagraphFormat.LineSpacingRule=0
  if($language -eq 'zh'){$contents.Font.NameFarEast='宋体'}
  $document.Repaginate()
  $document.TablesOfContents.Item(1).UpdatePageNumbers()
  $document.Save()
  $document.ExportAsFixedFormat($outputPath,17,$false,0,0,1,1,0,$true,$true,1,$true,$true,$false)
  $records[$language]=@{pages=$document.ComputeStatistics(2);tables=$document.Tables.Count;equations=$document.OMaths.Count;contents=$contents.Text}
  $document.Close(0)
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($document)
  $document=$null
 }
 $records|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $PSScriptRoot 'word-export-r2.json') -Encoding utf8
} finally {
 if($document){$document.Close(0);[void][Runtime.InteropServices.Marshal]::ReleaseComObject($document)}
 if($word){$word.Quit();[void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)}
}
& $PythonExecutable (Join-Path $PSScriptRoot 'sanitize_report_metadata.py')
if($LASTEXITCODE -ne 0){throw 'Report account metadata sanitization failed'}
