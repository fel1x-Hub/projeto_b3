# Etapa 7 — Interface (dashboard + chat IA + carteira)

## Objetivo
Construir a interface visual do sistema: dashboards com os dados e sinais, chat de IA contextualizado, e módulo de carteira pessoal. Tudo servido por uma API FastAPI que tanto o app web quanto o desktop consomem.

## Pré-requisito
Etapas 1–6 concluídas. O banco tem dados, sinais, ranking e relatórios gerados.

## 7.1 API backend (FastAPI)
Criar `src/api/` com endpoints que o frontend vai consumir. Planejar e documentar os endpoints ANTES de implementar. Endpoints mínimos:

| Endpoint | Descrição |
|----------|-----------|
| `GET /ranking` | Ranking do dia ou de uma data |
| `GET /ativo/{ticker}` | Dados, sinais e histórico de um ativo |
| `GET /mercado` | Resumo macro do dia |
| `GET /relatorio/{data}` | Relatório diário gerado na etapa 6 |
| `GET /carteira` | Posições e rendimentos do usuário |
| `POST /carteira/operacao` | Registrar compra ou venda manualmente |
| `POST /carteira/importar` | Importar extrato (CSV da XP ou outra corretora) |
| `POST /chat` | Enviar pergunta ao chat de IA |
| `GET /notificacoes` | Alertas e eventos do dia |

Regras:
- Autenticação local simples (token fixo em `.env`) para não deixar a API aberta.
- Todos os endpoints retornam JSON; erros retornam código HTTP adequado com mensagem clara.
- Swagger automático do FastAPI serve como documentação; manter atualizado.

## 7.2 Dashboard (React + Recharts + Tailwind)

> **Decisão do usuário (30/09/2026):** além do site em React, há um **app desktop em Qt (PySide6)** com as mesmas telas, consumindo a mesma API. Gráficos no Qt: QtCharts ou pyqtgraph.
Telas mínimas:

**Visão geral do mercado**
- Cards com Ibovespa, dólar, Selic, IPCA.
- Ranking do dia: tabela com score, variação, sentimento, volume anormal.
- Gráfico de barras: top 5 e bottom 5 do ranking.

**Detalhe do ativo**
- Gráfico de preço (candlestick ou linha), seleção de período.
- Painel de indicadores técnicos e fundamentalistas.
- Timeline de notícias e eventos relevantes.
- Histórico do score do ativo.

**Relatório diário**
- Renderização do markdown gerado na etapa 6.
- Botão de navegação entre datas.

**Carteira pessoal** (ver 7.3)

**Chat de IA** (ver 7.4)

Regras de UI:
- Design responsivo (funciona em janela desktop pequena e no navegador).
- Tema escuro por padrão (comum em ferramentas financeiras).
- Gráficos com Recharts; nada de bibliotecas de gráficos pesadas sem justificativa.
- Nenhuma chamada direta ao banco; tudo via API.

## 7.3 Módulo de carteira
**Entrada manual**
- Tela para registrar operações: ativo, tipo (compra/venda), data, quantidade, preço, corretagem.
- Posições calculadas a partir das operações (nunca armazenar posição diretamente; recalcular sempre).
- Preço médio, quantidade atual, custo total.

**Importação de extrato**
- Importar CSV no formato de exportação da XP Investimentos (e eventualmente outras corretoras).
- Antes de implementar, verificar se a XP oferece API oficial ou OAuth. Se não oferecer, usar importação de arquivo que o usuário exporta manualmente pelo site da corretora. Nunca pedir senha da corretora.
- Parser tolerante a variações de formato; alertar sobre linhas não reconhecidas sem descartar o resto.

**Acompanhamento**
- Valor atual da carteira (cotação em tempo real ou último fechamento).
- Rendimento por ativo: nominal e percentual, no dia, no mês, no ano e desde a compra.
- Comparação com Ibovespa no mesmo período.
- Gráfico de evolução do patrimônio.
- Alertas: ativo na carteira entrou no top ou bottom do ranking.

## 7.4 Chat de IA contextualizado
- Input de texto livre; o usuário pergunta sobre ativos, mercado, sua carteira ou pede análises.
- O backend monta o contexto antes de chamar o LLM: ranking do dia, sinais dos ativos mencionados, posições do usuário, relatório do dia, dados macro.
- O LLM responde com base nesse contexto; não inventa dados.
- Histórico da conversa mantido na sessão (não persiste entre recargas, por simplicidade).
- Avisos claros na interface: "Não é recomendação de investimento."
- Sugestões de perguntas pré-definidas para facilitar o uso.

## Testes
- Testes de endpoints da API (FastAPI TestClient, banco em memória).
- Testes de componentes React críticos (ranking table, carteira summary).
- Teste de importação de CSV com arquivo de exemplo anonimizado.

## Requisito do usuário: sempre atualizado (CLAUDE.md, regra 15)
- As telas se atualizam sozinhas (polling curto ou SSE), sem botão de atualizar e sem recarregar a página.
- Cada tela mostra "atualizado às HH:MM", se o mercado está aberto ou fechado, e o selo **provisório** nos valores intradiários.
- O detalhe do ativo mostra a situação do momento: preço e variação do dia, sinais recalculados e score/posição no ranking atuais.
- A API expõe quando cada dado foi atualizado (ex.: campo `atualizado_em` em cada resposta).

## Critério de pronto
- `uvicorn src.api.main:app` sobe sem erros e o Swagger abre.
- Todas as telas carregam com dados reais do banco.
- Carteira: registrar uma operação manual e ver o rendimento calculado.
- Importação de CSV: importar um extrato de exemplo e ver as posições.
- Chat: fazer uma pergunta sobre um ativo e receber resposta contextualizada.
- `pytest` passa nos testes de API.
