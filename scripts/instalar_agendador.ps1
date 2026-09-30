# Registra (ou remove) o agendador do projeto no Agendador de Tarefas do Windows,
# para ele iniciar sozinho quando você entrar no Windows, sem janela.
#
# Instalar:  powershell -ExecutionPolicy Bypass -File scripts\instalar_agendador.ps1
# Remover:   powershell -ExecutionPolicy Bypass -File scripts\instalar_agendador.ps1 -Remover
#
# A tarefa roda com o SEU usuário (sem privilégios de administrador) e só enquanto
# o PC estiver ligado. Na etapa 8 o mesmo papel passa para a nuvem.

param([switch]$Remover)

$nome = "ProjetoB3-Agendador"
$raiz = Split-Path -Parent $PSScriptRoot

if ($Remover) {
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Tarefa '$nome' removida."
    exit 0
}

$pythonw = Join-Path $raiz ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "Não encontrei $pythonw (crie o .venv primeiro)." }

$acao = New-ScheduledTaskAction -Execute $pythonw -Argument "scripts\agendador.py" -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$config = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $config `
    -Description "Projeto B3: atualiza cotações, sinais, ranking e relatório automaticamente" -Force | Out-Null
Start-ScheduledTask -TaskName $nome
Write-Output "Tarefa '$nome' registrada e iniciada. Log: $raiz\logs\app.log"
