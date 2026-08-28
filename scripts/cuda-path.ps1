function Find-CudaToolkit {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:CUDA_PATH) { $candidates.Add($env:CUDA_PATH) }

    $systemRoot = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    if (Test-Path -LiteralPath $systemRoot) {
        Get-ChildItem -LiteralPath $systemRoot -Directory -Filter "v13.*" |
            Sort-Object { [version]$_.Name.Substring(1) } -Descending |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    $candidates.Add((Join-Path $ProjectRoot ".cuda\v13.2"))
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath (Join-Path $candidate "bin\nvcc.exe"))) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}
