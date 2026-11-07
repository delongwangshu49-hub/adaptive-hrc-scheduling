param([Parameter(Mandatory)][string]$IdentitiesPath,[Parameter(Mandatory)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Publication.Gates.psm1') -Force
$base='a'*40; $commit='b'*40; $blob='d'*40; $tagObject='c'*40
$identities=@(Get-Content -LiteralPath  $IdentitiesPath  -Raw | ConvertFrom-Json)
$ciLog=(@(1..4 | ForEach-Object { $identities | ForEach-Object {"x ($_)" + ' ... ok'}; 'Ran 1299 tests in 1.000s' }) + @('All local CPU checks passed.','All local CPU checks passed.')) -join [char]10
$results=[Collections.Generic.List[object]]::new()
foreach($case in @(
 'push-success','release-success','fail-hash','fail-index','fail-commit','fail-tag','fail-push',
 'fail-run-list','fail-watch','wrong-origin','fail-log','fail-remote-tree','fail-release',
 'local-tag-exists','remote-tag-exists','wrong-base','wrong-new-commit','wrong-parent','wrong-staged-blob',
 'wrong-tag-target','wrong-ci-head','wrong-ci-conclusion','missing-ci-job','bad-ci-step',
 'missing-test-summary','missing-test-identity','wrong-remote-blob','wrong-remote-ref','wrong-asset-digest'
)) {
 $state=@{Trace=[Collections.Generic.List[string]]::new();Committed=$false}
 $meta=@{Base=$base;Tag='v1.1.0';Repository='owner/repo';Source=$PSScriptRoot;Packet=$PSScriptRoot;Tree=@{'sample.txt'=@{mode='100644';sha1=$blob}};Upserts=@('sample.txt');Deletes=@('PROMPT_LEDGER.md');TestIdentities=$identities;Attachments=@('payload.zip');AssetHashes=@{'payload.zip'=('e'*64)}}
 $phase=if($case -in @('push-success','fail-hash','fail-index','fail-commit','fail-tag','fail-push','local-tag-exists','remote-tag-exists','wrong-base','wrong-new-commit','wrong-parent','wrong-staged-blob','wrong-tag-target')){'CommitAndPush'}else{'Release'}
 $driver={
  param($tool,$arguments)
  $key=$tool+' '+($arguments -join ' ')
  $state.Trace.Add($key)
  $fail=@{'fail-hash'='git hash-object';'fail-index'='git update-index';'fail-commit'='git commit';'fail-tag'='git tag';'fail-push'='git push';'fail-run-list'='gh run list';'fail-watch'='gh run watch';'fail-run-view'='gh run view 91 --json';'fail-log'='gh run view 91 --log';'fail-remote-tree'='gh api repos/owner/repo/git/trees';'fail-release'='gh release create'}
  if($fail.ContainsKey($case) -and $key.StartsWith($fail[$case])){return @{ExitCode=7;Output='injected failure'}}
  $output=''
  switch -Regex ($key) {
   '^git remote get-url origin$' {$output=if($case -eq 'wrong-origin'){'https://github.com/other/repo'}else{if($phase -eq 'CommitAndPush'){'https://github.com/owner/repo.git'}else{'https://github.com/owner/repo'}};break}
   '^git branch ' {$output='main';break}
   '^git diff ' {$output='';break}
   '^git for-each-ref ' {$output=if($case -eq 'local-tag-exists'){'refs/tags/v1.1.0'}else{''};break}
   '^git hash-object ' {$output=$blob;break}
   '^git update-index ' {$output='';break}
   '^git ls-files ' {
    $staged=if($case -eq 'wrong-staged-blob'){'0'*40}else{$blob}
    $output='100644 '+$staged+' 0'+[char]9+'sample.txt'+[char]0;break
   }
   '^git commit ' {$state.Committed=$true;break}
   '^git rev-parse HEAD$' {
    $output=if($case -eq 'wrong-base'){'0'*40}elseif($phase -eq 'Release' -or $state.Committed){if($case -eq 'wrong-new-commit'){$base}else{$commit}}else{$base};break
   }
   '^git rev-parse [ab]{40}\^$' {$output=if($case -eq 'wrong-parent'){'0'*40}else{$base};break}
   '^git rev-parse refs/tags/' {$output=if($case -eq 'wrong-tag-target'){$base}else{$commit};break}
   '^git cat-file ' {$output='tag';break}
   '^git tag ' {$output='';break}
   '^git push ' {$output='';break}
   '^git ls-remote ' {
    if($phase -eq 'CommitAndPush') {
     $output=$base+[char]9+'refs/heads/main'
     if($case -eq 'remote-tag-exists'){$output += [char]10+$tagObject+[char]9+'refs/tags/v1.1.0'}
    } else {
     $target=if($case -eq 'wrong-remote-ref'){$base}else{$commit}
     $output=$commit+[char]9+'refs/heads/main'+[char]10+$target+[char]9+'refs/tags/v1.1.0^{}'
    };break
   }
   '^gh run list ' {$output=@(@{databaseId=91;headSha=$commit;event='push';workflowName='CPU checks';attempt=1})|ConvertTo-Json -Depth 4 -Compress;break}
   '^gh run watch ' {$output='';break}
   '^gh run view 91 --json ' {
    $jobs=@('CPU checks (ubuntu-24.04)','CPU checks (windows-2025)')|ForEach-Object {@{name=$_;conclusion='success';steps=@(@{name='Run shared checks';conclusion='success'})}}
    if($case -eq 'missing-ci-job'){$jobs=@($jobs[0])}
    if($case -eq 'bad-ci-step'){$jobs[0].steps[0].conclusion='failure'}
    $ciHead=if($case -eq 'wrong-ci-head'){$base}else{$commit}
    $conclusion=if($case -eq 'wrong-ci-conclusion'){'failure'}else{'success'}
    $output=@{headSha=$ciHead;event='push';attempt=1;status='completed';conclusion=$conclusion;jobs=@($jobs)}|ConvertTo-Json -Depth 8 -Compress;break
   }
   '^gh run view 91 --log$' {
    $output=$ciLog
    if($case -eq 'missing-test-summary'){$output=$ciLog.Replace('Ran 1299 tests in 1.000s','')}
    if($case -eq 'missing-test-identity'){$output=$ciLog.Replace('('+ $identities[0]+')','(unknown)')}
    break
   }
   '^gh api repos/owner/repo/git/commits/' {$output='{"tree":{"sha":"tree"}}';break}
   '^gh api repos/owner/repo/git/trees/' {
    $remoteBlob=if($case -eq 'wrong-remote-blob'){'0'*40}else{$blob}
    $output=@{truncated=$false;tree=@(@{type='blob';path='sample.txt';mode='100644';sha=$remoteBlob})}|ConvertTo-Json -Depth 5 -Compress;break
   }
   '^gh release create ' {$output='';break}
   '^gh api repos/owner/repo/releases/' {
    $digest=if($case -eq 'wrong-asset-digest'){'sha256:'+('0'*64)}else{'sha256:'+('e'*64)}
    $output=@{tag_name='v1.1.0';prerelease=$true;draft=$false;assets=@(@{name='payload.zip';digest=$digest})}|ConvertTo-Json -Depth 5 -Compress;break
   }
   default {throw "Unhandled simulated command: $key"}
  }
  return @{ExitCode=0;Output=$output}
 }.GetNewClosure()
 $errorText=$null
 try {$value=Invoke-PublicationFlow -Phase $phase -Meta $meta -Driver $driver}
 catch {$errorText=$_.Exception.Message}
 $success=$case -in @('push-success','release-success')
 if($success -and ($errorText -or $value -ne $commit)){throw "$case failed unexpectedly: $errorText"}
 if(-not $success -and -not $errorText){throw "$case incorrectly succeeded"}
 $trace=@($state.Trace)
 if(-not $success -and $case -notin @('fail-release','wrong-asset-digest') -and @($trace|Where-Object {$_ -like 'gh release create *'}).Count){throw "$case reached release"}
 if($case -in @('fail-hash','fail-index','fail-commit','wrong-base','local-tag-exists','remote-tag-exists','wrong-new-commit','wrong-parent','wrong-staged-blob') -and @($trace|Where-Object {$_ -like 'git tag *' -or $_ -like 'git push *'}).Count){throw "$case reached tag/push"}
 if($case -in @('fail-tag','wrong-tag-target') -and @($trace|Where-Object {$_ -like 'git push *'}).Count){throw "$case reached push"}
 $results.Add(@{case=$case;passed=$true;expected_failure=(-not $success);error=$errorText;commands=$trace})
}
$records=@{passed=$true;cases=$results.Count;real_git_writes=0;real_remote_writes=0;results=@($results)}
$records|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $OutputDirectory 'publication-tests.json') -Encoding utf8
"Passed $($results.Count) publication flow cases using simulated native drivers"
