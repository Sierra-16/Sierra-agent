param(
  [Parameter(Mandatory = $true)]
  [string]$InputPath,

  [string]$OutputDir = "tui/assets/sierra"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$root = Resolve-Path "."
$out = Join-Path $root $OutputDir
$framesDir = Join-Path $out "frames"
New-Item -ItemType Directory -Force -Path $framesDir | Out-Null

$sourcePath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $InputPath).Path)
$sheetPath = [System.IO.Path]::GetFullPath((Join-Path $out "sierra-spritesheet.png"))
if ($sourcePath -ne $sheetPath) {
  Copy-Item -LiteralPath $InputPath -Destination $sheetPath -Force
}

$frames = @(
  @{ name = "idle";  x = 76;  y = 58;  w = 230; h = 275 },
  @{ name = "spell"; x = 50;  y = 735; w = 260; h = 225 },
  @{ name = "aura";  x = 345; y = 710; w = 275; h = 255 },
  @{ name = "dash";  x = 635; y = 760; w = 255; h = 190 },
  @{ name = "calm";  x = 930; y = 750; w = 230; h = 220 },
  @{ name = "aim";   x = 355; y = 418; w = 285; h = 250 },
  @{ name = "cast";  x = 630; y = 418; w = 300; h = 245 }
)

function Color-ToHex([System.Drawing.Color]$c) {
  "#{0:x2}{1:x2}{2:x2}" -f $c.R, $c.G, $c.B
}

function Color-Distance([System.Drawing.Color]$a, [System.Drawing.Color]$b) {
  $dr = [int]$a.R - [int]$b.R
  $dg = [int]$a.G - [int]$b.G
  $db = [int]$a.B - [int]$b.B
  [Math]::Sqrt(($dr * $dr) + ($dg * $dg) + ($db * $db))
}

function Is-VisiblePixel([System.Drawing.Color]$c, [System.Drawing.Color]$bg) {
  if ($c.A -lt 20) { return $false }
  $distance = Color-Distance $c $bg
  $sat = $c.GetSaturation()
  $brightness = $c.GetBrightness()
  $maxChannel = [Math]::Max($c.R, [Math]::Max($c.G, $c.B))
  $minChannel = [Math]::Min($c.R, [Math]::Min($c.G, $c.B))
  $channelSpread = $maxChannel - $minChannel
  if ($minChannel -gt 215 -and $channelSpread -lt 55) { return $false }
  if ($minChannel -gt 185 -and $channelSpread -lt 52 -and $distance -lt 115) { return $false }
  if ($distance -lt 70 -and $sat -lt 0.34 -and $brightness -gt 0.50) { return $false }
  if ($sat -lt 0.22 -and $brightness -gt 0.68) { return $false }
  if ($sat -lt 0.12 -and $brightness -gt 0.46) { return $false }
  return $true
}

function Average-Corners([System.Drawing.Bitmap]$bitmap) {
  $points = @(
    @(0, 0),
    @(($bitmap.Width - 1), 0),
    @(0, ($bitmap.Height - 1)),
    @(($bitmap.Width - 1), ($bitmap.Height - 1))
  )
  $r = 0
  $g = 0
  $b = 0
  foreach ($p in $points) {
    $c = $bitmap.GetPixel($p[0], $p[1])
    $r += $c.R
    $g += $c.G
    $b += $c.B
  }
  [System.Drawing.Color]::FromArgb(
    [Math]::Round($r / 4),
    [Math]::Round($g / 4),
    [Math]::Round($b / 4)
  )
}

function Trim-SpriteBounds([System.Drawing.Bitmap]$bitmap, [System.Drawing.Color]$bg) {
  $minX = $bitmap.Width
  $minY = $bitmap.Height
  $maxX = 0
  $maxY = 0

  for ($y = 0; $y -lt $bitmap.Height; $y++) {
    for ($x = 0; $x -lt $bitmap.Width; $x++) {
      if (Is-VisiblePixel ($bitmap.GetPixel($x, $y)) $bg) {
        if ($x -lt $minX) { $minX = $x }
        if ($y -lt $minY) { $minY = $y }
        if ($x -gt $maxX) { $maxX = $x }
        if ($y -gt $maxY) { $maxY = $y }
      }
    }
  }

  if ($minX -ge $bitmap.Width -or $minY -ge $bitmap.Height) {
    return [System.Drawing.Rectangle]::new(0, 0, $bitmap.Width, $bitmap.Height)
  }

  $pad = 7
  $left = [Math]::Max(0, $minX - $pad)
  $top = [Math]::Max(0, $minY - $pad)
  $right = [Math]::Min($bitmap.Width - 1, $maxX + $pad)
  $bottom = [Math]::Min($bitmap.Height - 1, $maxY + $pad)
  [System.Drawing.Rectangle]::new($left, $top, $right - $left + 1, $bottom - $top + 1)
}

function Resize-Bitmap([System.Drawing.Bitmap]$bitmap, [int]$targetW, [int]$targetH) {
  $resized = [System.Drawing.Bitmap]::new($targetW, $targetH)
  $graphics = [System.Drawing.Graphics]::FromImage($resized)
  $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
  $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
  $graphics.DrawImage($bitmap, 0, 0, $targetW, $targetH)
  $graphics.Dispose()
  $resized
}

function New-TransparentBitmap([System.Drawing.Bitmap]$bitmap, [System.Drawing.Color]$bg) {
  $transparent = [System.Drawing.Bitmap]::new(
    $bitmap.Width,
    $bitmap.Height,
    [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
  )

  for ($y = 0; $y -lt $bitmap.Height; $y++) {
    for ($x = 0; $x -lt $bitmap.Width; $x++) {
      $pixel = $bitmap.GetPixel($x, $y)
      if (Is-VisiblePixel $pixel $bg) {
        $transparent.SetPixel($x, $y, [System.Drawing.Color]::FromArgb($pixel.A, $pixel.R, $pixel.G, $pixel.B))
      } else {
        $transparent.SetPixel($x, $y, [System.Drawing.Color]::Transparent)
      }
    }
  }

  $transparent
}

function New-Run($text, $fg, $bg) {
  $run = [ordered]@{ text = $text }
  if ($fg) { $run.fg = $fg }
  if ($bg) { $run.bg = $bg }
  $run
}

$upperHalfBlock = [string][char]0x2580
$lowerHalfBlock = [string][char]0x2584

function Convert-ToTerminalFrame([System.Drawing.Bitmap]$bitmap, [string]$name) {
  $bg = Average-Corners $bitmap
  $trim = Trim-SpriteBounds $bitmap $bg
  $cropped = $bitmap.Clone($trim, $bitmap.PixelFormat)

  $maxW = 24
  $maxH = 28
  $scale = [Math]::Min($maxW / $cropped.Width, $maxH / $cropped.Height)
  $targetW = [Math]::Max(8, [Math]::Round($cropped.Width * $scale))
  $targetH = [Math]::Max(8, [Math]::Round($cropped.Height * $scale))
  if ($targetH % 2 -eq 1) { $targetH += 1 }

  $small = Resize-Bitmap $cropped $targetW $targetH
  $smallBg = Average-Corners $small
  $lines = @()

  for ($y = 0; $y -lt $small.Height; $y += 2) {
    $line = @()
    $currentText = ""
    $currentFg = $null
    $currentBg = $null

    for ($x = 0; $x -lt $small.Width; $x++) {
      $top = $small.GetPixel($x, $y)
      $bottom = $small.GetPixel($x, [Math]::Min($y + 1, $small.Height - 1))
      $topVisible = Is-VisiblePixel $top $smallBg
      $bottomVisible = Is-VisiblePixel $bottom $smallBg

      $char = " "
      $fg = $null
      $bgColor = $null

      if ($topVisible -and $bottomVisible) {
        $char = $upperHalfBlock
        $fg = Color-ToHex $top
        $bgColor = Color-ToHex $bottom
      } elseif ($topVisible) {
        $char = $upperHalfBlock
        $fg = Color-ToHex $top
      } elseif ($bottomVisible) {
        $char = $lowerHalfBlock
        $fg = Color-ToHex $bottom
      }

      if ($currentText.Length -gt 0 -and $fg -eq $currentFg -and $bgColor -eq $currentBg) {
        $currentText += $char
      } else {
        if ($currentText.Length -gt 0) {
          $line += New-Run $currentText $currentFg $currentBg
        }
        $currentText = $char
        $currentFg = $fg
        $currentBg = $bgColor
      }
    }

    if ($currentText.Length -gt 0) {
      $line += New-Run $currentText $currentFg $currentBg
    }
    $lines += ,$line
  }

  $small.Dispose()
  $cropped.Dispose()

  [ordered]@{
    name = $name
    width = $targetW
    height = [int]($targetH / 2)
    lines = $lines
  }
}

$source = [System.Drawing.Bitmap]::FromFile($InputPath)
$terminalFrames = @()
try {
  foreach ($frame in $frames) {
    $rect = [System.Drawing.Rectangle]::new($frame.x, $frame.y, $frame.w, $frame.h)
    $crop = $source.Clone($rect, $source.PixelFormat)
    $transparentCrop = New-TransparentBitmap $crop (Average-Corners $crop)
    $transparentCrop.Save((Join-Path $framesDir "$($frame.name).png"), [System.Drawing.Imaging.ImageFormat]::Png)
    $transparentCrop.Dispose()
    $terminalFrames += Convert-ToTerminalFrame $crop $frame.name
    $crop.Dispose()
  }
} finally {
  $source.Dispose()
}

$payload = [ordered]@{
  source = "sierra-spritesheet.png"
  generatedAt = (Get-Date).ToString("s")
  frames = $terminalFrames
}

$json = $payload | ConvertTo-Json -Depth 100
[System.IO.File]::WriteAllText((Join-Path $out "terminal-frames.json"), $json, [System.Text.UTF8Encoding]::new($false))

Write-Host "Generated $($terminalFrames.Count) Sierra terminal frames in $out"
