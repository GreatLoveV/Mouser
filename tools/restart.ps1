# Quits the running Mouser (if any) and starts it again in the background, without a window.
$session = "$env:APPDATA\Mouser\session.json"
if (Test-Path $session) {
    $s = Get-Content $session | ConvertFrom-Json
    try { Invoke-RestMethod "http://127.0.0.1:$($s.port)/api/quit" -Method Post -Headers @{ 'X-Mouser-Token' = $s.token } -ContentType 'application/json' -Body '{}' | Out-Null } catch {}
    Start-Sleep -Seconds 2
}
Start-Process (Get-Command pythonw).Source -ArgumentList '-I', "`"$PSScriptRoot\..\run.pyw`"", '--background' -WorkingDirectory "$PSScriptRoot\.."
Start-Sleep -Seconds 3
$s = Get-Content $session | ConvertFrom-Json
"Mouser running on port $($s.port)"
