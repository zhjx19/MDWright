# MDEditor contenteditable + annotations + LLM e2e (CDP over PowerShell WebSocket) - v2
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$edge = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
if (-not (Test-Path $edge)) { $edge = 'C:\Program Files\Microsoft\Edge\Application\msedge.exe' }
$port = 9225
$url = 'http://127.0.0.1:18766/?file=C%3A%5CUsers%5Csm001%5CAppData%5CLocal%5CTemp%5Cmda_e2e%5C%E6%89%B9%E6%B3%A8%E6%B5%8B%E8%AF%95.md'
$profile = 'C:\Users\sm001\AppData\Local\Temp\mda_cdp_e2e'
if (Test-Path $profile) { Remove-Item $profile -Recurse -Force -ErrorAction SilentlyContinue }

$p = Start-Process -FilePath $edge -PassThru -ArgumentList @(
  '--headless=new', '--disable-gpu', '--no-first-run',
  "--remote-debugging-port=$port",
  "--user-data-dir=$profile",
  '--window-size=1400,900',
  $url)

$target = $null
for ($i = 0; $i -lt 40; $i++) {
  try {
    $list = Invoke-RestMethod "http://127.0.0.1:$port/json/list" -TimeoutSec 2
    $target = $list | Where-Object { $_.type -eq 'page' -and $_.url -like '*18766*' } | Select-Object -First 1
    if ($target) { break }
  } catch {}
  Start-Sleep -Milliseconds 500
}
if (-not $target) { Write-Output 'FAIL | no CDP target'; exit 1 }

$ws = New-Object System.Net.WebSockets.ClientWebSocket
[void]($ws.ConnectAsync([Uri]$target.webSocketDebuggerUrl, [Threading.CancellationToken]::None).GetAwaiter().GetResult())

$script:nextId = 0
$script:pageErrors = 0
$buf = New-Object byte[] 262144

function Send-Cdp($method, $params) {
  $script:nextId++
  $o = @{ id = $script:nextId; method = $method }
  if ($params) { $o.params = $params }
  $json = $o | ConvertTo-Json -Depth 6 -Compress
  $bytes = [Text.Encoding]::UTF8.GetBytes($json)
  $seg = New-Object ArraySegment[byte] (,$bytes)
  [void]($ws.SendAsync($seg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, [Threading.CancellationToken]::None).GetAwaiter().GetResult())
  return $script:nextId
}

function Read-Cdp($sec) {
  $sb = New-Object Text.StringBuilder
  $deadline = [DateTime]::UtcNow.AddSeconds($sec)
  do {
    $remain = $deadline - [DateTime]::UtcNow
    if ($remain.TotalMilliseconds -le 0) { return $null }
    $ct = New-Object Threading.CancellationTokenSource([int]$remain.TotalMilliseconds)
    try {
      $seg = New-Object ArraySegment[byte] (,$buf)
      $r = $ws.ReceiveAsync($seg, $ct.Token).GetAwaiter().GetResult()
      if ($r.Count -gt 0) { [void]$sb.Append([Text.Encoding]::UTF8.GetString($buf, 0, $r.Count)) }
    } catch { return $null }
  } while (-not $r.EndOfMessage)
  return ($sb.ToString() | ConvertFrom-Json)
}

function Eval($expr, $waitSec) {
  if (-not $waitSec) { $waitSec = 20 }
  $id = Send-Cdp 'Runtime.evaluate' @{ expression = $expr; returnByValue = $true }
  $deadline = [DateTime]::UtcNow.AddSeconds($waitSec)
  while ([DateTime]::UtcNow -lt $deadline) {
    $m = Read-Cdp 15
    if ($null -eq $m) { continue }
    if ($m.id -eq $id) {
      if ($m.result.exceptionDetails) { $script:pageErrors++ }
      return $m.result.result.value
    }
    if ($m.method -eq 'Runtime.exceptionThrown') { $script:pageErrors++ }
  }
  return $null
}

[void](Send-Cdp 'Runtime.enable' $null)
[void](Send-Cdp 'Log.enable' $null)
Start-Sleep -Seconds 4

$FAILS = @()
function Check($name, $cond, $detail) {
  if ($cond) { Write-Output "PASS | $name" }
  else { Write-Output "FAIL | $name | $detail"; $script:FAILS += $name }
}

# ---- A: boot state ----
$jsA = @'
JSON.stringify({tag:document.getElementById('editor').tagName,
 spans:document.querySelectorAll('#editor span[data-aid]').length,
 statAnns:document.getElementById('statAnns').textContent,
 statChars:document.getElementById('statChars').textContent,
 pblk:document.querySelectorAll('#preview .pblk').length,
 statFile:document.getElementById('statFile').textContent,
 edLen:document.getElementById('editor').textContent.length})
'@
$a = Eval $jsA
$A = $a | ConvertFrom-Json
Check 'A1 editor is DIV' ($A.tag -eq 'DIV') $a
Check 'A2 reanchored spans=2' ($A.spans -eq 2) $a
Check 'A3 statAnns=2' ($A.statAnns -eq '批注 2') $a
Check 'A4 chars counted' ($A.statChars -match '^[1-9]') $a
Check 'A5 preview blocks rendered' ($A.pblk -ge 2) $a
Check 'A6 file loaded' ($A.statFile -eq '批注测试.md') $a

# ---- B: click annotation span opens modal ----
$jsB = @'
var sp=document.querySelector('span[data-aid=t1]');
if(!sp){'NO_SPAN'} else {
  sp.click();
  JSON.stringify({vis:!document.getElementById('annOverlay').hidden,
    quote:document.getElementById('annQuote').textContent,
    note:document.getElementById('annNote').value})
}
'@
$b = Eval $jsB
if ($b -eq 'NO_SPAN') { Check 'B span click' $false 'span t1 not found' }
else {
  $B = $b | ConvertFrom-Json
  Check 'B1 annModal opens' $B.vis $b
  Check 'B2 quote correct' ($B.quote -eq '一句需要被批注的话') $b
  Check 'B3 note loaded' ($B.note -like '预置批注一*') $b
  [void](Eval "document.getElementById('annOk').click(); 'closed'")
}

# ---- C: stale annotation pruned server-side ----
Start-Sleep -Seconds 2
$c = Invoke-RestMethod 'http://127.0.0.1:18766/api/annotations?path=C%3A%5CUsers%5Csm001%5CAppData%5CLocal%5CTemp%5Cmda_e2e%5C%E6%89%B9%E6%B3%A8%E6%B5%8B%E8%AF%95.md'
$ids = @($c.annotations | ForEach-Object { $_.id })
Check 'C1 stale t3 pruned' (-not ($ids -contains 't3')) ($ids -join ',')
Check 'C2 t1 t2 kept' (($ids -contains 't1') -and ($ids -contains 't2')) ($ids -join ',')

# ---- D: select text -> selTools -> create annotation ----
$jsD = @'
var w=document.createTreeWalker(document.getElementById('editor'),NodeFilter.SHOW_TEXT,null),n,hit=null;
while((n=w.nextNode())){ var i=n.nodeValue.indexOf('用于验证编辑器的基本渲染能力'); if(i>=0){ hit=[n,i]; break; } }
if(!hit){'NO_TEXT'} else {
  var r=document.createRange(); r.setStart(hit[0],hit[1]); r.setEnd(hit[0],hit[1]+14);
  var s=window.getSelection(); s.removeAllRanges(); s.addRange(r);
  document.getElementById('editor').dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
  'SEL_OK'
}
'@
$d = Eval $jsD
Check 'D1 selection made' ($d -eq 'SEL_OK') $d
Start-Sleep -Milliseconds 300
$d2 = Eval "JSON.stringify({vis:!document.getElementById('selTools').hidden})"
$D2 = $d2 | ConvertFrom-Json
Check 'D2 selTools visible' ($D2.vis -eq $true) $d2
$jsD3 = @'
document.getElementById('selNote').click();
JSON.stringify({spans:document.querySelectorAll('#editor span[data-aid]').length,
  statAnns:document.getElementById('statAnns').textContent,
  quote:document.getElementById('annQuote').textContent,
  overlay:!document.getElementById('annOverlay').hidden})
'@
$d3 = Eval $jsD3
$D3 = $d3 | ConvertFrom-Json
Check 'D3 new span wrapped' ($D3.spans -eq 3) $d3
Check 'D4 statAnns=3' ($D3.statAnns -eq '批注 3') $d3
Check 'D5 modal shows selection' ($D3.quote -eq '用于验证编辑器的基本渲染能力') $d3
Check 'D6 annOverlay opens' ($D3.overlay -eq $true) $d3
[void](Eval "document.getElementById('annNote').value='手工新增批注OK'; document.getElementById('annOk').click(); 'done'")

# ---- E: annotation persisted with note ----
Start-Sleep -Seconds 2
$e = Invoke-RestMethod 'http://127.0.0.1:18766/api/annotations?path=C%3A%5CUsers%5Csm001%5CAppData%5CLocal%5CTemp%5Cmda_e2e%5C%E6%89%B9%E6%B3%A8%E6%B5%8B%E8%AF%95.md'
$newAnn = @($e.annotations | Where-Object { $_.note -eq '手工新增批注OK' })
Check 'E1 new annotation persisted' ($newAnn.Count -eq 1) (($e.annotations | ConvertTo-Json -Compress).Substring(0,[Math]::Min(160,($e.annotations | ConvertTo-Json -Compress).Length)))
Check 'E2 total 3 on server' (@($e.annotations).Count -eq 3) (@($e.annotations).Count)

# ---- F: polish flow (real LM Studio qwen3-8b) ----
$jsF = @'
var w=document.createTreeWalker(document.getElementById('editor'),NodeFilter.SHOW_TEXT,null),n,hit=null;
while((n=w.nextNode())){ var i=n.nodeValue.indexOf('这是第一段正文'); if(i>=0){ hit=[n,i]; break; } }
if(!hit){'NO_TEXT'} else {
  var r=document.createRange(); r.setStart(hit[0],hit[1]); r.setEnd(hit[0],hit[1]+7);
  var s=window.getSelection(); s.removeAllRanges(); s.addRange(r);
  document.getElementById('editor').dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
  'SEL_OK'
}
'@
$f = Eval $jsF
Check 'F1 select for polish' ($f -eq 'SEL_OK') $f
Start-Sleep -Milliseconds 300
[void](Eval "document.getElementById('selPolish').click(); 'clicked'")
Start-Sleep -Milliseconds 500
$f2 = Eval "JSON.stringify({overlay:!document.getElementById('rwOverlay').hidden, orig:document.getElementById('rwOrig').textContent, dis:document.getElementById('rwNew').disabled})"
$F2 = $f2 | ConvertFrom-Json
Check 'F2 rwModal opens' ($F2.overlay -eq $true) $f2
Check 'F3 orig quoted' ($F2.orig -eq '这是第一段正文') $f2
$polished = $null
for ($i = 0; $i -lt 80; $i++) {
  Start-Sleep -Seconds 2
  $v = Eval "JSON.stringify({dis:document.getElementById('rwNew').disabled, val:document.getElementById('rwNew').value})"
  $V = $v | ConvertFrom-Json
  if (-not $V.dis -and $V.val -and $V.val -notlike '*润色中*') { $polished = $V.val; break }
}
Check 'F4 LLM polish returned' ($null -ne $polished -and $polished.Length -gt 0) 'timeout or empty'
if ($polished) {
  Write-Output ("INFO | polished: " + $polished.Substring(0, [Math]::Min(60, $polished.Length)))
  $pj = $polished | ConvertTo-Json -Compress
  [void](Eval "window.__p=$pj; 'set'")
  [void](Eval "document.getElementById('rwOk').click(); 'replaced'")
  Start-Sleep -Milliseconds 600
  $f6 = Eval "JSON.stringify({hasOld:document.getElementById('editor').textContent.indexOf('这是第一段正文')>=0, hasNew:document.getElementById('editor').textContent.indexOf(window.__p)>=0, t1alive:!!document.querySelector('span[data-aid=t1]'), pblk:document.querySelectorAll('#preview .pblk').length})"
  $F6 = $f6 | ConvertFrom-Json
  Check 'F5 old text replaced' ($F6.hasOld -eq $false) $f6
  Check 'F6 new text present' ($F6.hasNew -eq $true) $f6
  Check 'F7 neighbor ann t1 survived' ($F6.t1alive -eq $true) $f6
}

# ---- G: LLM config modal with real model list ----
[void](Eval "document.getElementById('btnLLM').click(); 'opened'")
Start-Sleep -Seconds 5
$g = Eval "JSON.stringify({vis:!document.getElementById('llmOverlay').hidden, backend:document.getElementById('llmBackend').value, base:document.getElementById('llmBase').value, models:document.getElementById('llmModel').options.length, sel:document.getElementById('llmModel').value, timeout:document.getElementById('llmTimeout').value})"
$G = $g | ConvertFrom-Json
Check 'G1 llmModal opens' ($G.vis -eq $true) $g
Check 'G2 backend loaded' ($G.backend -eq 'lmstudio') $g
Check 'G3 base_url loaded' ($G.base -eq 'http://localhost:1234') $g
Check 'G4 models fetched' ($G.models -ge 3) $g
Check 'G5 model selected' ($G.sel -eq 'qwen3-8b') $g
Check 'G6 timeout loaded' ($G.timeout -eq '120') $g
[void](Eval "document.getElementById('llmClose').click(); 'closed'")

# ---- H: no legacy textarea, no page errors ----
$h = Eval "!!document.querySelector('textarea#editor')"
Check 'H1 no legacy textarea' ($h -eq $false) "found=$h"
Check 'H2 no page exceptions' ($script:pageErrors -eq 0) "errors=$($script:pageErrors)"

try { [void]($ws.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, 'done', [Threading.CancellationToken]::None).GetAwaiter().GetResult()) } catch {}
try { $p.Kill() } catch {}

if ($FAILS.Count -eq 0) { Write-Output 'ALL PASS' } else { Write-Output ("FAILED: " + ($FAILS -join ', ')) }