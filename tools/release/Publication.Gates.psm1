Set-StrictMode -Version Latest

function Invoke-CheckedNative {
    param([string]$Tool, [string[]]$Arguments, [scriptblock]$Driver)
    if ($Driver) { $result = & $Driver $Tool $Arguments } else {
        $ErrorActionPreference = 'Stop'
        $PSNativeCommandUseErrorActionPreference = $false
        $output = (& $Tool @Arguments 2>&1 | ForEach-Object { "$_" }) -join "`n"
        $result = @{ ExitCode = $LASTEXITCODE; Output = $output }
    }
    if ($null -eq $result -or $result.ExitCode -ne 0) { throw "Native command failed: $Tool $($Arguments -join ' '); exit $($result.ExitCode)" }
    return [string]$result.Output
}

function Assert-Equal {
    param($Actual, $Expected, [string]$Reason)
    if ([string]$Actual -cne [string]$Expected) { throw $Reason }
}

function Assert-Tree {
    param([string]$Raw, $Expected)
    $actual = @{}
    foreach ($line in $Raw.TrimEnd("`r","`n").Split([char]0, [StringSplitOptions]::RemoveEmptyEntries)) {
        if ($line -notmatch '^([0-9]{6}) ([0-9a-f]{40}) 0\t(.+)$') { throw 'Unmerged or invalid index entry' }
        if ($actual.ContainsKey($Matches[3])) { throw 'Duplicate staged path' }
        $actual[$Matches[3]] = "$($Matches[1])/$($Matches[2])"
    }
    Assert-Equal $actual.Count $Expected.Count 'Staged tree inventory differs'
    foreach ($name in $Expected.Keys) {
        if (-not $actual.ContainsKey($name)) { throw "Missing staged path: $name" }
        Assert-Equal $actual[$name] "$($Expected[$name].mode)/$($Expected[$name].sha1)" "Staged bytes/mode differ: $name"
    }
}

function Assert-CIRun {
    param($Run, [string]$Commit)
    Assert-Equal $Run.headSha $Commit 'CI commit differs'
    Assert-Equal $Run.event 'push' 'CI event differs'
    Assert-Equal $Run.attempt 1 'CI attempt differs'
    Assert-Equal $Run.status 'completed' 'CI incomplete'
    Assert-Equal $Run.conclusion 'success' 'CI failed'
    Assert-Equal @($Run.jobs).Count 2 'CI job inventory differs'
    foreach ($name in @('CPU checks (ubuntu-24.04)', 'CPU checks (windows-2025)')) {
        $job = @($Run.jobs | Where-Object { $_.name -ceq $name })
        Assert-Equal $job.Count 1 "CI job missing: $name"
        Assert-Equal $job[0].conclusion 'success' "CI job failed: $name"
        $step = @($job[0].steps | Where-Object { $_.name -ceq 'Run shared checks' })
        Assert-Equal $step.Count 1 'Shared check step missing'
        Assert-Equal $step[0].conclusion 'success' 'Shared check step failed'
    }
}

function Assert-CILog {
    param([string]$Log, [string[]]$Identities)
    Assert-Equal $Identities.Count 1299 'Reviewed test inventory differs'
    Assert-Equal ([regex]::Matches($Log, 'Ran 1299 tests in [0-9.]+s').Count) 4 'Four complete test summaries required'
    Assert-Equal ([regex]::Matches($Log, 'All local CPU checks passed\.').Count) 2 'Shared entry completion missing'
    if ($Log -match 'FAILED \((failures|errors)=') { throw 'Failed tests in CI log' }
    $seen = @{}
    # A test may print a diagnostic between its identity and its terminal "ok".
    # The four complete successful shared entries establish the result; retain
    # every identity even when its status is on a later log line.
    foreach ($m in [regex]::Matches($Log, '\((test_[A-Za-z0-9_.]+)\)')) {
        $id = $m.Groups[1].Value
        if (-not $seen.ContainsKey($id)) { $seen[$id] = 0 }
        $seen[$id]++
    }
    Assert-Equal $seen.Count $Identities.Count 'CI identity inventory differs'
    foreach ($id in $Identities) { Assert-Equal $seen[$id] 4 "CI identity count differs: $id" }
}

function Assert-RemoteTree {
    param($Response, $Expected)
    if ($Response.truncated) { throw 'Remote tree truncated' }
    $blobs = @($Response.tree | Where-Object { $_.type -ceq 'blob' })
    Assert-Equal $blobs.Count $Expected.Count 'Remote tree inventory differs'
    foreach ($entry in $blobs) {
        if (-not $Expected.ContainsKey($entry.path)) { throw 'Unexpected remote path' }
        Assert-Equal $entry.sha $Expected[$entry.path].sha1 "Remote blob differs: $($entry.path)"
        Assert-Equal $entry.mode $Expected[$entry.path].mode "Remote mode differs: $($entry.path)"
    }
}

function Invoke-PublicationFlow {
    param([ValidateSet('CommitAndPush','Release')][string]$Phase, $Meta, [scriptblock]$Driver)
    $native = { param($Tool,$Arguments) Invoke-CheckedNative -Tool $Tool -Arguments $Arguments -Driver $Driver }
    $base = $Meta.Base; $tag = $Meta.Tag; $repo = $Meta.Repository
    $origin = (& $native git @('remote','get-url','origin')).Trim().TrimEnd('/')
    $origin = $origin -replace '\.git$', ''
    Assert-Equal $origin ("https://github.com/"+$repo) 'Publication origin differs'
    Assert-Equal (& $native git @('branch','--show-current')).Trim() 'main' 'Wrong branch'
    Assert-Equal (& $native git @('diff','--cached','--name-only')).Trim() '' 'Staged paths exist'
    if ($Phase -ceq 'CommitAndPush') {
        Assert-Equal (& $native git @('rev-parse','HEAD')).Trim() $base 'Base differs'
        $refs = & $native git @('for-each-ref','--format=%(refname)','refs/tags')
        if ($refs.Split("`n") -contains "refs/tags/$tag") { throw 'Local proposed tag exists' }
        $remote = (& $native git @('ls-remote','origin','refs/heads/main',"refs/tags/$tag","refs/tags/$tag^{}")).Trim()
        Assert-Equal $remote "$base`trefs/heads/main" 'Remote base/tag differs'
        foreach ($name in $Meta.Upserts) {
            $row = $Meta.Tree[$name]; $file = Join-Path $Meta.Source $name
            $blob = (& $native git @('hash-object','-w','--no-filters','--',$file)).Trim()
            Assert-Equal $blob $row.sha1 "Reviewed blob differs: $name"
            [void](& $native git @('update-index','--add','--cacheinfo',"$($row.mode),$blob,$name"))
        }
        foreach ($name in $Meta.Deletes) { [void](& $native git @('update-index','--force-remove','--',$name)) }
        Assert-Tree (& $native git @('ls-files','--stage','-z')) $Meta.Tree
        [void](& $native git @('commit','-F',(Join-Path $Meta.Packet 'commit-message.txt')))
        $commit = (& $native git @('rev-parse','HEAD')).Trim()
        if ($commit -notmatch '^[a-f0-9]{40}$' -or $commit -ceq $base) { throw 'No new publication commit' }
        Assert-Equal (& $native git @('rev-parse',"$commit^")).Trim() $base 'Publication parent differs'
        Assert-Tree (& $native git @('ls-files','--stage','-z')) $Meta.Tree
        [void](& $native git @('tag','-a',$tag,'-F',(Join-Path $Meta.Packet 'tag-message.txt'),$commit))
        Assert-Equal (& $native git @('cat-file','-t',"refs/tags/$tag")).Trim() 'tag' 'Not annotated tag'
        Assert-Equal (& $native git @('rev-parse',"refs/tags/$tag^{}")).Trim() $commit 'Tag target differs'
        [void](& $native git @('push','--atomic','origin','main',"refs/tags/$tag"))
        return $commit
    }
    $commit = (& $native git @('rev-parse','HEAD')).Trim()
    if ($commit -ceq $base -or $commit -notmatch '^[a-f0-9]{40}$') { throw 'No approved publication commit' }
    Assert-Equal (& $native git @('rev-parse',"$commit^")).Trim() $base 'Publication parent differs'
    Assert-Equal (& $native git @('cat-file','-t',"refs/tags/$tag")).Trim() 'tag' 'Not annotated tag'
    Assert-Equal (& $native git @('rev-parse',"refs/tags/$tag^{}")).Trim() $commit 'Tag target differs'
    Assert-Tree (& $native git @('ls-files','--stage','-z')) $Meta.Tree
    $runs = (& $native gh @('run','list','--commit',$commit,'--event','push','--json','databaseId,headSha,event,workflowName,attempt') | ConvertFrom-Json)
    $selected = @($runs | Where-Object { $_.headSha -ceq $commit -and $_.event -ceq 'push' -and $_.workflowName -ceq 'CPU checks' -and $_.attempt -eq 1 })
    Assert-Equal $selected.Count 1 'Unique reviewed push run not found'
    $runId = [string]$selected[0].databaseId
    [void](& $native gh @('run','watch',$runId,'--exit-status'))
    $run = & $native gh @('run','view',$runId,'--json','headSha,event,status,conclusion,attempt,jobs')
    Assert-CIRun ($run | ConvertFrom-Json) $commit
    Assert-CILog (& $native gh @('run','view',$runId,'--log')) $Meta.TestIdentities
    $remoteCommit = (& $native gh @('api',"repos/$repo/git/commits/$commit") | ConvertFrom-Json)
    $tree = (& $native gh @('api',"repos/$repo/git/trees/$($remoteCommit.tree.sha)?recursive=1") | ConvertFrom-Json)
    Assert-RemoteTree $tree $Meta.Tree
    $refs = & $native git @('ls-remote','origin','refs/heads/main',"refs/tags/$tag^{}")
    $lines = @($refs.Trim().Split("`n") | ForEach-Object { $_.TrimEnd("`r") })
    if ($lines -notcontains "$commit`trefs/heads/main" -or $lines -notcontains "$commit`trefs/tags/$tag^{}" -or $lines.Count -ne 2) { throw 'Remote refs differ' }
    $arguments = @('release','create',$tag)
    $arguments += @($Meta.Attachments | ForEach-Object { Join-Path $Meta.Packet ('public/'+$_) })
    $arguments += @('--verify-tag','--prerelease','--target',$commit,'--title','v1.1.0 W5 integration candidate','--notes-file',(Join-Path $Meta.Packet 'GITHUB-RELEASE-NOTES.md'))
    [void](& $native gh $arguments)
    $release = (& $native gh @('api',"repos/$repo/releases/tags/$tag") | ConvertFrom-Json)
    Assert-Equal $release.tag_name $tag 'Published tag differs'
    if (-not $release.prerelease -or $release.draft) { throw 'Wrong release visibility/type' }
    Assert-Equal @($release.assets).Count $Meta.Attachments.Count 'Published attachment inventory differs'
    foreach ($asset in $release.assets) {
        if (-not $Meta.AssetHashes.ContainsKey($asset.name)) { throw 'Unexpected published asset' }
        Assert-Equal $asset.digest ('sha256:'+$Meta.AssetHashes[$asset.name]) "Published digest differs: $($asset.name)"
    }
    return $commit
}

function Get-ReviewedMetadata {
    param([string]$Packet,[string]$Source,[string]$ApprovedManifestSha256)
    $packetRoot = (Resolve-Path -LiteralPath $Packet).Path; $sourceRoot = (Resolve-Path -LiteralPath $Source).Path
    $manifestFile = Join-Path $packetRoot 'REVIEW-ARTIFACTS.json'
    Assert-Equal (Get-FileHash -LiteralPath $manifestFile -Algorithm SHA256).Hash.ToLowerInvariant() $ApprovedManifestSha256.ToLowerInvariant() 'Approved review identity differs'
    $manifest = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json -AsHashtable
    foreach ($name in $manifest.files.Keys) {
        if ($name -match '(^|/)\.\.(/|$)|^[\\/]|:') { throw 'Unsafe review path' }
        Assert-Equal (Get-FileHash -LiteralPath (Join-Path $packetRoot $name) -Algorithm SHA256).Hash.ToLowerInvariant() $manifest.files[$name].sha256 "Review artifact differs: $name"
    }
    $inventory = Get-Content -LiteralPath (Join-Path $packetRoot 'public/SOURCE-MANIFEST.json') -Raw | ConvertFrom-Json -AsHashtable
    $actual = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Force)
    Assert-Equal $actual.Count $inventory.Count 'Extract source into a fresh directory'
    foreach ($name in $inventory.Keys) {
        if ($name -match '(^|/)\.\.(/|$)|^[\\/]|:') { throw 'Unsafe source path' }
        $p = Join-Path $sourceRoot $name
        if ((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source reparse point' }
        Assert-Equal (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() $inventory[$name].sha256 "Reviewed source differs: $name"
    }
    $attachments = (Get-Content -LiteralPath (Join-Path $packetRoot 'ATTACHMENTS.json') -Raw | ConvertFrom-Json).files
    $hashes = @{}
    foreach ($name in $attachments) { $hashes[$name] = (Get-FileHash -LiteralPath (Join-Path $packetRoot ('public/'+$name)) -Algorithm SHA256).Hash.ToLowerInvariant() }
    return @{
        Base = '27c5c34de14c41dcbc2e8d4e1f9fe327d9966df6'; Tag = 'v1.1.0'; Repository = 'delongwangshu49-hub/adaptive-hrc-scheduling'
        Packet = $packetRoot; Source = $sourceRoot
        Tree = (Get-Content -LiteralPath (Join-Path $packetRoot 'PUBLIC-TREE.json') -Raw | ConvertFrom-Json -AsHashtable)
        Upserts = @(Get-Content -LiteralPath (Join-Path $packetRoot 'UPSERT-PATHS.txt'))
        Deletes = @(Get-Content -LiteralPath (Join-Path $packetRoot 'DELETED_PATHS.txt'))
        Attachments = @($attachments); AssetHashes = $hashes
        TestIdentities = @(Get-Content -LiteralPath (Join-Path $packetRoot 'EXPECTED-TESTS.json') -Raw | ConvertFrom-Json)
    }
}
Export-ModuleMember -Function Invoke-CheckedNative,Invoke-PublicationFlow,Get-ReviewedMetadata
