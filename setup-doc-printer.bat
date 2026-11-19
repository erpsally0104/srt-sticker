@echo off
setlocal
net session >nul 2>&1
if %errorlevel% NEQ 0 (
  echo Requesting administrator rights...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$f=Get-Content -LiteralPath '%~f0' -Raw; $m=[char]35+'REGION:PS'; $i=$f.IndexOf($m); if($i -lt 0){Write-Host 'Embedded script missing.'; exit 1}; Invoke-Expression $f.Substring($i)"
exit /b %errorlevel%

#REGION:PS
# ------------------------------------------------------------------
# SRT Labels - document printer network setup
# Switches the HP document printer from a WSD port to a Standard
# TCP/IP port, turns off SNMP status polling (so a sleeping printer
# is not shown "offline"), and opens the printer web page so you can
# raise its Power Save timer. It does NOT touch the TSC label printer.
# Everything is reversible; the revert command is printed at the end.
# ------------------------------------------------------------------
$ErrorActionPreference = 'Stop'
try { $Host.UI.RawUI.WindowTitle = 'SRT - Document printer setup' } catch {}

# IP discovered during setup; used only as the fallback default.
$defaultIp = '192.168.0.9'

$rxUrl = [regex]'https?://((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})'
$rxIp  = [regex]'^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$'

function Done($code) { Write-Host ''; Read-Host 'Press Enter to close'; exit $code }
function Say($t, $c) { if ($c) { Write-Host $t -ForegroundColor $c } else { Write-Host $t } }

try {
  Say '============================================='
  Say ' SRT Labels - document printer network setup'
  Say '============================================='
  Say ''
  Say 'Run this on the shop computer that runs run.bat, with the HP'
  Say 'document printer installed on it. It will not change the TSC'
  Say 'label printer.'
  Say ''

  # 1) Choose the HP document printer -------------------------------
  $skip = 'OneNote|Microsoft|XPS|Fax|PDF|TSC|TE244|TTP'
  $all  = @(Get-Printer | Where-Object { $_.Name -notmatch $skip })
  $hp   = @($all | Where-Object { $_.Name -match 'HP|Hewlett|LaserJet|Laser 3' -or $_.DriverName -match 'HP|Hewlett|IPP' })
  if ($hp.Count -eq 0) { $hp = $all }
  if ($hp.Count -eq 0) { Say 'No usable printers are installed on this computer.' Red; Done 1 }

  if ($hp.Count -eq 1) {
    $printer = $hp[0]
  } else {
    Say 'Printers found:'
    for ($k = 0; $k -lt $hp.Count; $k++) { Say ("  [{0}] {1}   (port {2})" -f ($k + 1), $hp[$k].Name, $hp[$k].PortName) }
    $pick = Read-Host 'Pick the HP document printer by number'
    $n = 0
    if (-not [int]::TryParse($pick, [ref]$n) -or $n -lt 1 -or $n -gt $hp.Count) { Say 'Invalid choice.' Red; Done 1 }
    $printer = $hp[$n - 1]
  }
  $origPort = $printer.PortName

  # 2) Work out the printer's IP address ----------------------------
  $ip = $null
  $cp = Get-PrinterPort -Name $origPort -ErrorAction SilentlyContinue
  if ($cp -and $cp.PrinterHostAddress) { $ip = $cp.PrinterHostAddress }
  if (-not $ip) {
    foreach ($d in (Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match 'HP|Laser|Hewlett' })) {
      foreach ($pr in (Get-PnpDeviceProperty -InstanceId $d.InstanceId -ErrorAction SilentlyContinue)) {
        $hit = $rxUrl.Match("$($pr.Data)")
        if ($hit.Success) { $ip = $hit.Groups[1].Value; break }
      }
      if ($ip) { break }
    }
  }
  if (-not $ip) { $ip = $defaultIp }

  $ans = Read-Host ("Printer IP address [{0}]" -f $ip)
  if ($ans.Trim()) { $ip = $ans.Trim() }
  if (-not $rxIp.IsMatch($ip)) { Say 'That is not an IPv4 address.' Red; Done 1 }

  $portName = "IP_$ip"
  $reuse = Get-PrinterPort | Where-Object { $_.PrinterHostAddress -eq $ip } | Select-Object -First 1
  if ($reuse) { $portName = $reuse.Name }

  # 3) Show the plan and confirm ------------------------------------
  Say ''
  Say '--- Plan ---------------------------------------------------'
  Say ("  Printer      : {0}" -f $printer.Name) Cyan
  Say ("  Current port : {0}" -f $origPort)
  Say ("  New port     : {0}  ->  {1}:9100 (RAW, SNMP off)" -f $portName, $ip) Cyan
  Say '  Then: restart Print Spooler, open the printer web page for'
  Say '  the Power Save setting, and offer a test page.'
  Say ''
  if ((Read-Host 'Proceed? (y/N)') -notmatch '^[Yy]') { Say 'Cancelled. Nothing was changed.' Yellow; Done 0 }

  # 4) Reachability check (does not fail the run) -------------------
  Say ''
  Say ("Checking {0} on port 9100..." -f $ip)
  $ok = $false
  try { $c = New-Object System.Net.Sockets.TcpClient; $ok = $c.ConnectAsync($ip, 9100).Wait(3000); $c.Close() } catch { $ok = $false }
  if ($ok) { Say '  reachable.' Green }
  else {
    Say '  not answering right now (it may be asleep or on a different IP).' Yellow
    if ((Read-Host '  Continue anyway? (y/N)') -notmatch '^[Yy]') { Done 1 }
  }

  # 5) Create the Standard TCP/IP port if needed --------------------
  if ($reuse) {
    Say ("Using existing TCP/IP port {0}" -f $portName) Green
  } else {
    if (Get-PrinterPort -Name $portName -ErrorAction SilentlyContinue) { $portName = "IP_${ip}_srt" }
    Say ("Creating TCP/IP port {0}" -f $portName)
    Add-PrinterPort -Name $portName -PrinterHostAddress $ip
  }

  # 6) RAW 9100 + SNMP status polling off ---------------------------
  $reg = "HKLM:\SYSTEM\CurrentControlSet\Control\Print\Monitors\Standard TCP/IP Port\Ports\$portName"
  if (Test-Path $reg) {
    New-ItemProperty -Path $reg -Name 'SNMP Enabled' -PropertyType DWord -Value 0    -Force | Out-Null
    New-ItemProperty -Path $reg -Name 'Protocol'     -PropertyType DWord -Value 1    -Force | Out-Null
    New-ItemProperty -Path $reg -Name 'Port Number'  -PropertyType DWord -Value 9100 -Force | Out-Null
    Say '  SNMP status polling off, RAW 9100 set.' Green
  }

  # 7) Point the printer at the port --------------------------------
  if ($origPort -ne $portName) {
    Set-Printer -Name $printer.Name -PortName $portName
    Say ("Printer moved onto {0}." -f $portName) Green
  } else {
    Say 'Printer was already on this port.' Green
  }

  # 8) Restart the spooler so the SNMP/port change takes effect -----
  Say 'Restarting the Print Spooler (cancels any jobs waiting right now)...'
  Restart-Service -Name Spooler -Force
  Start-Sleep -Seconds 2
  $now = Get-Printer -Name $printer.Name
  Say ("Now: {0}  port {1}  status {2}" -f $now.Name, $now.PortName, $now.PrinterStatus) Cyan

  # 9) Power Save - open the printer web page with steps ------------
  Say ''
  Say '--- Keep it awake (printer web page) -----------------------'
  Say 'Opening the printer page in your browser. To raise the sleep timer:'
  Say '  1. Click Login (top right). The admin password is blank by'
  Say '     default - just submit, then set a password afterwards.'
  Say '  2. Settings / Machine Settings -> System Setup -> Power Save.'
  Say '  3. Set it to the longest value (180 minutes) or Off, then Apply.'
  Say '  Leave Auto Power Off DISABLED.'
  Say '  (On the printer itself: Menu -> System Setup -> Power Save.)'
  try { Start-Process ("http://{0}/" -f $ip) } catch { Say ("  Open http://{0}/ by hand." -f $ip) Yellow }

  Say ''
  Say '--- Also do this (router) ----------------------------------'
  Say ("Reserve {0} for the printer in your router (DHCP reservation)," -f $ip)
  Say 'so the address cannot change and break the port above.'

  # 10) Optional Windows test page ----------------------------------
  Say ''
  if ((Read-Host 'Print a Windows test page now? (y/N)') -match '^[Yy]') {
    try { & rundll32 printui.dll,PrintUIEntry /k /n "$($printer.Name)"; Say 'Test page sent.' Green }
    catch { Say ("Could not start the test page: {0}" -f $_.Exception.Message) Yellow }
  }

  Say ''
  Say 'Done.' Green
  Say 'To undo the port change later, run this in an admin PowerShell:' DarkGray
  Say ("  Set-Printer -Name '{0}' -PortName '{1}'" -f $printer.Name, $origPort) DarkGray
  Done 0
}
catch {
  Say ''
  Say ("ERROR: {0}" -f $_.Exception.Message) Red
  Say 'Re-run the file to try again. No further changes were made.' Yellow
  Done 1
}
