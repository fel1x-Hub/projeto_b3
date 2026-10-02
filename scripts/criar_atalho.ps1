# Cria o atalho "Projeto B3" na Área de Trabalho, que abre o app desktop sem janela de console.
# Uso: powershell -ExecutionPolicy Bypass -File scripts\criar_atalho.ps1
$raiz = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $raiz ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "Não encontrei $pythonw (crie o .venv primeiro)." }
$destino = Join-Path ([Environment]::GetFolderPath("Desktop")) "Projeto B3.lnk"
$atalho = (New-Object -ComObject WScript.Shell).CreateShortcut($destino)
$atalho.TargetPath = $pythonw
$atalho.Arguments = "desktop\main.py"
$atalho.WorkingDirectory = $raiz
$atalho.Description = "Projeto B3: ranking, carteira e chat (apoio à decisão)"
$atalho.Save()
Write-Output "Atalho criado: $destino"
