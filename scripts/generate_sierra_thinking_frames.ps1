param(
  [string]$InputPath = "tui/assets/sierra/thinking-symbol-spritesheet.png",

  [string]$OutputDir = "tui/assets/sierra"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$root = Resolve-Path "."
$input = Resolve-Path $InputPath
$out = Join-Path $root $OutputDir
$framesDir = Join-Path $out "thinking"
New-Item -ItemType Directory -Force -Path $framesDir | Out-Null

$frameNames = @(
  "think-idle",
  "think-dot-1",
  "think-dot-2",
  "think-dot-3",
  "think-question",
  "think-question-spark",
  "think-idea",
  "think-sparkle"
)
$upperHalfBlock = [string][char]0x2580
$lowerHalfBlock = [string][char]0x2584

function Color-ToHex([System.Drawing.Color]$c) {
  "#{0:x2}{1:x2}{2:x2}" -f $c.R, $c.G, $c.B
}

function Color-Distance([System.Drawing.Color]$a, [System.Drawing.Color]$b) {
  $dr = [int]$a.R - [int]$b.R
  $dg = [int]$a.G - [int]$b.G
  $db = [int]$a.B - [int]$b.B
  [Math]::Sqrt(($dr * $dr) + ($dg * $dg) + ($db * $db))
}

function Is-VisiblePixel([System.Drawing.Color]$c, [System.Drawing.Color]$key) {
  if ($c.A -lt 20) { return $false }
  if ((Color-Distance $c $key) -lt 45) { return $false }
  return $true
}

function Trim-SpriteBounds([System.Drawing.Bitmap]$bitmap, [System.Drawing.Color]$key) {
  $minX = $bitmap.Width
  $minY = $bitmap.Height
  $maxX = 0
  $maxY = 0

  for ($y = 0; $y -lt $bitmap.Height; $y++) {
    for ($x = 0; $x -lt $bitmap.Width; $x++) {
      if (Is-VisiblePixel ($bitmap.GetPixel($x, $y)) $key) {
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

  $pad = 10
  $left = [Math]::Max(0, $minX - $pad)
  $top = [Math]::Max(0, $minY - $pad)
  $right = [Math]::Min($bitmap.Width - 1, $maxX + $pad)
  $bottom = [Math]::Min($bitmap.Height - 1, $maxY + $pad)
  [System.Drawing.Rectangle]::new($left, $top, $right - $left + 1, $bottom - $top + 1)
}

function Resize-Bitmap([System.Drawing.Bitmap]$bitmap, [int]$targetW, [int]$targetH) {
  $resized = [System.Drawing.Bitmap]::new($targetW, $targetH)
  $graphics = [System.Drawing.Graphics]::FromImage($resized)
  $graphics.Clear([System.Drawing.Color]::Magenta)
  $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
  $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
  $graphics.DrawImage($bitmap, 0, 0, $targetW, $targetH)
  $graphics.Dispose()
  $resized
}

function New-Run($text, $fg, $bg) {
  $run = [ordered]@{ text = $text }
  if ($fg) { $run.fg = $fg }
  if ($bg) { $run.bg = $bg }
  $run
}

function Convert-ToTerminalFrame([System.Drawing.Bitmap]$bitmap, [string]$name, [System.Drawing.Color]$key) {
  $trim = Trim-SpriteBounds $bitmap $key
  $cropped = $bitmap.Clone($trim, $bitmap.PixelFormat)

  $maxW = 18
  $maxH = 20
  $scale = [Math]::Min($maxW / $cropped.Width, $maxH / $cropped.Height)
  $targetW = [Math]::Max(8, [Math]::Round($cropped.Width * $scale))
  $targetH = [Math]::Max(8, [Math]::Round($cropped.Height * $scale))
  if ($targetH % 2 -eq 1) { $targetH += 1 }

  $small = Resize-Bitmap $cropped $targetW $targetH
  $lines = @()

  for ($y = 0; $y -lt $small.Height; $y += 2) {
    $line = @()
    $currentText = ""
    $currentFg = $null
    $currentBg = $null

    for ($x = 0; $x -lt $small.Width; $x++) {
      $top = $small.GetPixel($x, $y)
      $bottom = $small.GetPixel($x, [Math]::Min($y + 1, $small.Height - 1))
      $topVisible = Is-VisiblePixel $top $key
      $bottomVisible = Is-VisiblePixel $bottom $key

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

$source = [System.Drawing.Bitmap]::FromFile($input)
$terminalFrames = @()
try {
  $key = $source.GetPixel(0, 0)
  $cellCount = $frameNames.Count
  $cellWidth = [int][Math]::Floor($source.Width / $cellCount)

  for ($i = 0; $i -lt $cellCount; $i++) {
    $x = $i * $cellWidth
    $w = if ($i -eq ($cellCount - 1)) { $source.Width - $x } else { $cellWidth }
    $rect = [System.Drawing.Rectangle]::new($x, 0, $w, $source.Height)
    $crop = $source.Clone($rect, $source.PixelFormat)
    $name = $frameNames[$i]
    $crop.Save((Join-Path $framesDir "$name.png"), [System.Drawing.Imaging.ImageFormat]::Png)
    $terminalFrames += Convert-ToTerminalFrame $crop $name $key
    $crop.Dispose()
  }
} finally {
  $source.Dispose()
}

$payload = [ordered]@{
  source = "thinking-chibi-spritesheet.png"
  generatedAt = (Get-Date).ToString("s")
  frames = $terminalFrames
}

$json = $payload | ConvertTo-Json -Depth 100
[System.IO.File]::WriteAllText((Join-Path $out "thinking-terminal-frames.json"), $json, [System.Text.UTF8Encoding]::new($false))

Write-Host "Generated $($terminalFrames.Count) Sierra thinking terminal frames in $out"
