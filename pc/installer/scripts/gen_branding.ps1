# Generate CyberStream installer branding bitmaps via System.Drawing.
#
# Required NSIS Modern UI 2 sizes:
#   welcome.bmp : 164 x 314 (left panel)
#   header.bmp  : 150 x 57  (top-right)
# Both must be BMP3 (24-bit RGB, no alpha).
#
# Design language: minimal modern, lots of negative space, soft radial glow.
# No grid, no L-brackets, no terminal prompts. Mute the saturation; let the
# typography breathe. Win11-ish.

param(
    [string]$OutputDir = (Join-Path (Split-Path -Parent $PSScriptRoot) 'branding')
)

Add-Type -AssemblyName System.Drawing

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

function Paint-RadialGlow {
    param(
        $G,
        [int]$Cx,
        [int]$Cy,
        [int]$Radius,
        [System.Drawing.Color]$InnerColor,
        [System.Drawing.Color]$OuterColor
    )
    $rect = New-Object System.Drawing.Rectangle ($Cx - $Radius), ($Cy - $Radius), ($Radius * 2), ($Radius * 2)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddEllipse($rect)
    $brush = New-Object System.Drawing.Drawing2D.PathGradientBrush $path
    $brush.CenterColor = $InnerColor
    $brush.SurroundColors = @($OuterColor)
    $G.FillEllipse($brush, $rect)
    $brush.Dispose()
    $path.Dispose()
}

function New-WelcomeBitmap {
    param([int]$Width, [int]$Height, [string]$OutPath)

    $bmp = New-Object System.Drawing.Bitmap $Width, $Height, ([System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
    $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality

    # Solid near-black background. Win11 fluent dark surfaces sit around this value.
    $bgC = [System.Drawing.Color]::FromArgb(255, 12, 12, 18)
    $bgBrush = New-Object System.Drawing.SolidBrush $bgC
    $g.FillRectangle($bgBrush, 0, 0, $Width, $Height)
    $bgBrush.Dispose()

    # Two soft glows — purple top-left, cyan bottom-right. Low alpha so they
    # diffuse rather than burn.
    $purpleGlow = [System.Drawing.Color]::FromArgb(70, 140, 80, 220)
    $cyanGlow   = [System.Drawing.Color]::FromArgb(70, 60, 200, 230)
    Paint-RadialGlow $g 35 80  130 $purpleGlow $bgC
    Paint-RadialGlow $g ($Width - 35) ($Height - 80) 140 $cyanGlow $bgC

    # Hairline divider near the top (1px, 30% alpha).
    $hairColor = [System.Drawing.Color]::FromArgb(50, 200, 200, 230)
    $hairPen = New-Object System.Drawing.Pen($hairColor, [single]1)
    $g.DrawLine($hairPen, 16, 36, ($Width - 16), 36)
    $hairPen.Dispose()

    # Top-left mark: small filled square (cyan) — minimalist app glyph stand-in.
    $markBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 0, 200, 230))
    $g.FillRectangle($markBrush, 16, 16, 12, 12)
    $markBrush.Dispose()

    # Top-left wordmark — small caps, tracking-y but elegant.
    $wmFont = New-Object System.Drawing.Font 'Segoe UI', 8, ([System.Drawing.FontStyle]::Bold)
    $wmBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(220, 220, 230, 240))
    $g.DrawString('CYBERSTREAM', $wmFont, $wmBrush, 34, 17)
    $wmFont.Dispose()
    $wmBrush.Dispose()

    # Centerpiece: a single, soft cyan ring. Modern, no extra ornament.
    $ringColor = [System.Drawing.Color]::FromArgb(180, 0, 200, 230)
    $ringPen = New-Object System.Drawing.Pen($ringColor, [single]1.5)
    $g.DrawEllipse($ringPen, ($Width / 2 - 32), 130, 64, 64)
    $ringPen.Dispose()

    # Inner dot at ring center
    $dotBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 200, 80, 230))
    $g.FillEllipse($dotBrush, ($Width / 2 - 3), 159, 6, 6)
    $dotBrush.Dispose()

    # Headline + subtitle, centered, breathing room above and below.
    $sf = New-Object System.Drawing.StringFormat
    $sf.Alignment = [System.Drawing.StringAlignment]::Center

    $titleFont = New-Object System.Drawing.Font 'Segoe UI Variable Display', 16, ([System.Drawing.FontStyle]::Regular)
    if ($null -eq $titleFont -or $titleFont.Name -ne 'Segoe UI Variable Display') {
        # Fall back if the variable font isn't registered (older systems).
        $titleFont = New-Object System.Drawing.Font 'Segoe UI', 16, ([System.Drawing.FontStyle]::Regular)
    }
    $titleBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 240, 240, 248))
    $g.DrawString('CyberStream', $titleFont, $titleBrush, ($Width / 2), 218, $sf)
    $titleFont.Dispose()
    $titleBrush.Dispose()

    $subFont = New-Object System.Drawing.Font 'Segoe UI', 8, ([System.Drawing.FontStyle]::Regular)
    $subBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(160, 200, 200, 220))
    $g.DrawString('Personal Media Nexus', $subFont, $subBrush, ($Width / 2), 246, $sf)
    $subFont.Dispose()
    $subBrush.Dispose()

    # Bottom hairline divider + faint version line.
    $hairPen = New-Object System.Drawing.Pen($hairColor, [single]1)
    $g.DrawLine($hairPen, 16, 282, ($Width - 16), 282)
    $hairPen.Dispose()

    $tinyFont = New-Object System.Drawing.Font 'Segoe UI', 7
    $tinyBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(140, 180, 180, 200))
    $g.DrawString('Setup Wizard', $tinyFont, $tinyBrush, ($Width / 2), 290, $sf)
    $tinyFont.Dispose()
    $tinyBrush.Dispose()

    $sf.Dispose()

    $bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Bmp)
    $g.Dispose()
    $bmp.Dispose()

    Write-Host "wrote $OutPath ($Width x $Height)"
}

function New-HeaderBitmap {
    param([int]$Width, [int]$Height, [string]$OutPath)

    $bmp = New-Object System.Drawing.Bitmap $Width, $Height, ([System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit

    # MUI header is rendered against the page chrome (light or dark) — keeping
    # it dark with a single accent works on either theme.
    $bgC = [System.Drawing.Color]::FromArgb(255, 12, 12, 18)
    $bgBrush = New-Object System.Drawing.SolidBrush $bgC
    $g.FillRectangle($bgBrush, 0, 0, $Width, $Height)
    $bgBrush.Dispose()

    # Soft accent glow on the right edge.
    $glow = [System.Drawing.Color]::FromArgb(80, 0, 200, 230)
    Paint-RadialGlow $g ($Width - 12) ($Height / 2) 36 $glow $bgC

    # Small accent square + wordmark on the left.
    $markBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 0, 200, 230))
    $g.FillRectangle($markBrush, 10, 22, 12, 12)
    $markBrush.Dispose()

    $wmFont = New-Object System.Drawing.Font 'Segoe UI', 9, ([System.Drawing.FontStyle]::Bold)
    $wmBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 240, 240, 248))
    $g.DrawString('CyberStream', $wmFont, $wmBrush, 28, 20)
    $wmFont.Dispose()
    $wmBrush.Dispose()

    $bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Bmp)
    $g.Dispose()
    $bmp.Dispose()

    Write-Host "wrote $OutPath ($Width x $Height)"
}

New-WelcomeBitmap -Width 164 -Height 314 -OutPath (Join-Path $OutputDir 'welcome.bmp')
New-HeaderBitmap  -Width 150 -Height  57 -OutPath (Join-Path $OutputDir 'header.bmp')

Write-Host ''
Write-Host 'Branding bitmaps generated.'
