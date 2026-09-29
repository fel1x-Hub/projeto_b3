# Etapa 6 — Relatório diário

## Objetivo
Gerar um relatório diário legível que explique o ranking, os sinais e as notícias relevantes.

## Tarefas
1. Coletar os insumos do dia: ranking, principais sinais de cada ativo do topo e do fundo, notícias e eventos relevantes, contexto macro.
2. O LLM recebe esses dados já calculados (em JSON) e escreve o texto. Ele NÃO recalcula números; todo número no relatório vem dos dados fornecidos.
3. Estrutura sugerida:
   - Resumo do dia e contexto macro
   - Top e bottom do ranking, com os fatores que mais pesaram
   - Notícias e eventos relevantes por ativo
   - Riscos e pontos de atenção
   - Desempenho do paper trading até o momento
   - Aviso de que é material de apoio, não recomendação de investimento
4. Checagem automática: números citados no texto batem com os dados de entrada.
5. Saída em Markdown e/ou HTML, salva em `relatorios/AAAA-MM-DD.md`.
6. `scripts/rodar_diario.py` que encadeia coleta → sinais → ranking → paper trading → relatório, com log e tratamento de falhas.
7. Instruções de agendamento (cron no Linux/Mac ou Agendador de Tarefas no Windows).

## Critério de pronto
- Relatório gerado para os últimos 5 pregões sem erros de números.
- Pipeline diário completo roda com um único comando.
- README com instruções de instalação, configuração e uso.
