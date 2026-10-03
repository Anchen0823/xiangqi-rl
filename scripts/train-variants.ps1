param([ValidateSet('custom','jieqi','banqi','all')][string]$Mode='all',[string]$Output='runs/variants/short-training',[int]$Nodes=32,[int]$Steps=100)
# Compatibility entry for existing commands and desktop shortcuts.
& (Join-Path $PSScriptRoot 'variants/train-variants.ps1') -Mode $Mode -Output $Output -Nodes $Nodes -Steps $Steps
