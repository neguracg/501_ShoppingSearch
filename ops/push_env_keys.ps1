# Copy the Rakuten keys (and, only with -IncludeYahoo, YAHOO_CLIENT_ID) from the local .env to the VPS .env without printing them.
# Default (no switch) is exactly the old behaviour: the two RAKUTEN_ lines only. -IncludeYahoo is for after the owner decides to publish Yahoo (consumption ticket #1169).
# YAHOO_CLIENT_ID is read from .env, or else from .env.yahoo.local (local PoC file, never committed).
param([switch]$IncludeYahoo)
# The VPS IP is read at run time from C:\Claude\VPS\docs\infra\CONNECTION.md (not stored in this public repo).
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repo '.env'
$yahooLocal = Join-Path $repo '.env.yahoo.local'
$conn = 'C:\Claude\VPS\docs\infra\CONNECTION.md'
$key = Join-Path $env:USERPROFILE '.ssh\negura_deploy'

$ip = (Select-String -Path $conn -Pattern 'グローバルIP\s*\|\s*`([0-9.]+)`' -Encoding UTF8).Matches[0].Groups[1].Value
if (-not $ip) { throw 'VPS IP not found in CONNECTION.md' }

$names = @('RAKUTEN_APPLICATION_ID', 'RAKUTEN_ACCESS_KEY')
if ($IncludeYahoo) { $names += 'YAHOO_CLIENT_ID' }
$pattern = '^(' + ($names -join '|') + ')='
$lines = @(Get-Content -Path $envPath -Encoding UTF8 | Where-Object { $_ -match $pattern })
if ($IncludeYahoo -and -not ($lines | Where-Object { $_ -match '^YAHOO_CLIENT_ID=' }) -and (Test-Path $yahooLocal)) {
    $lines += @(Get-Content -Path $yahooLocal -Encoding UTF8 | Where-Object { $_ -match '^YAHOO_CLIENT_ID=' })
}
if ($lines.Count -ne $names.Count) { throw "expected $($names.Count) key lines, found $($lines.Count)" }
foreach ($l in $lines) { $n, $v = $l -split '=', 2; Write-Host ("{0}: length {1}" -f $n, $v.Trim().Length) }

$tmp = [System.IO.Path]::GetTempFileName()
try {
    [System.IO.File]::WriteAllText($tmp, (($lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding $false))
    & scp -i $key -o BatchMode=yes $tmp "deploy@${ip}:/tmp/kaimono_keys"
    if ($LASTEXITCODE -ne 0) { throw 'scp failed' }
} finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

$excludes = ($names | ForEach-Object { "-e '^$_='" }) -join ' '
$remote = "cd /opt/apps/kaimono && grep -v $excludes .env > .env.new && cat /tmp/kaimono_keys >> .env.new && chmod 600 .env.new && mv .env.new .env && rm -f /tmp/kaimono_keys && grep -c '^RAKUTEN_' .env"
& ssh -i $key -o BatchMode=yes "deploy@$ip" $remote
if ($LASTEXITCODE -ne 0) { throw 'remote update failed' }
Write-Host "OK: $($names.Count) keys written to /opt/apps/kaimono/.env (values not shown). Tell Claude 'done'."
