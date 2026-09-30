# CLAUDE.md — Sistema de Análise da B3

## O que é este projeto
Sistema pessoal de apoio à análise da bolsa brasileira (B3). Coleta dados de várias fontes (cotações, macro, documentos da CVM, notícias), extrai sinais com código e IA, gera um ranking diário de ativos e um relatório explicando o porquê.

**É uma ferramenta de apoio à decisão, NÃO um robô que opera sozinho.** Nunca implemente envio de ordens a corretoras.

## Como trabalhar neste projeto
1. Veja a tabela de status abaixo e identifique a etapa atual.
2. Leia o arquivo da etapa atual em `etapas/etapaN.md` antes de qualquer coisa.
3. **Planeje primeiro**: apresente o plano da etapa e espere aprovação antes de codar.
4. Implemente em passos pequenos, rodando os testes a cada passo.
5. Ao terminar, confira o "Critério de pronto" da etapa, mostre os resultados e atualize a tabela de status.
6. Não comece a próxima etapa sem aprovação.

**Autorização do usuário (30/09/2026): modo contínuo.** O Claude pode emendar uma etapa na outra sem esperar aprovação do plano. Regras desse modo:
- Ao **começar** cada etapa, avisar o usuário em uma mensagem curta: qual etapa começou, o plano resumido e as decisões tomadas por padrão.
- Continuar parando para o que é **decisão do usuário**:
  - a regra da carteira do backtest, antes de ver resultados (etapa 5);
  - a fonte de cotação intradiária, grátis ou paga (etapa 6);
  - o extrato de exemplo da XP (etapa 7);
  - a escolha de hospedagem e a criação de contas (etapa 8, regra 13);
  - qualquer gasto de dinheiro.
- Continua valendo: confirmar o critério de pronto, atualizar o status, commit e push a cada passo e testes verdes.
- O roteiro detalhado do que falta está em "Próximos passos", abaixo.

## Etapas
| # | Etapa | Arquivo | Status |
|---|-------|---------|--------|
| 1 | Fundação e banco de dados | [etapas/etapa1.md](etapas/etapa1.md) | ✅ concluída |
| 2 | Coleta de dados | [etapas/etapa2.md](etapas/etapa2.md) | ✅ concluída |
| 3 | Extração de sinais | [etapas/etapa3.md](etapas/etapa3.md) | ✅ concluída |
| 4 | Modelo de ranking | [etapas/etapa4.md](etapas/etapa4.md) | 🔨 em andamento |
| 5 | Backtest e paper trading | [etapas/etapa5.md](etapas/etapa5.md) | ⏳ pendente |
| 6 | Relatório diário | [etapas/etapa6.md](etapas/etapa6.md) | ⏳ pendente |
| 7 | Interface (dashboard + chat IA + carteira) | [etapas/etapa7.md](etapas/etapa7.md) | ⏳ pendente |
| 8 | Deploy (desktop .exe + web gratuito) | [etapas/etapa8.md](etapas/etapa8.md) | ⏳ pendente |

Status possíveis: ⏳ pendente · 🔨 em andamento · ✅ concluída

## Configuração do usuário
- Universo (decisão do usuário, 30/09/2026): **a maior parte da B3**, e não uma lista fixa.
  - Entram **ações e units** (ON, PN e units em lote padrão). Ficam de fora FIIs, ETFs e BDRs; o BOVA11 fica só como benchmark.
  - Filtro de liquidez **ponto-no-tempo**: volume financeiro médio ≥ **R$ 100 mil/dia** nos últimos 3 meses, avaliado em cada data. Empresas que saíram da bolsa continuam no histórico, para evitar viés de sobrevivência.
  - `config/ativos.csv` passa a ser só a lista de exceções (incluir ou excluir à mão). Também guarda apelidos de busca em notícias e CNPJs que a CVM não resolve.
  - Implementado: ~530 papéis detectados em 5 anos de arquivos da B3; ~250 passam no filtro hoje, ~290 em 2024 e ~320 em 2022.
- Feeds de notícias em `config/feeds.csv`.
- Hardware: 16 GB RAM, GPU Intel UHD integrada (sem CUDA), ~200 GB livres. Sem GPU: sentimento com modelo pronto em CPU ou LLM via API; fine-tuning local inviável.
- Experiência: intermediário
- Python: 3.13, ambiente virtual em `.venv`
- Repositório: https://github.com/fel1x-Hub/projeto_b3 (branch `main`, commits regulares por passo)

## Próximos passos (roteiro vivo, atualizar a cada etapa)
Legenda: 🟢 decisão padrão do Claude (pode ser mudada pelo usuário) · 🙋 decisão do usuário (parar e perguntar)

**Rotinas em andamento (não bloqueiam as próximas etapas)**
- Eventos: `python scripts/extrair_eventos.py`.
  - Títulos de todos os fatos relevantes, em lote.
  - Depois, o texto completo, por liquidez. Avança alguns dias pela cota grátis do Gemini e melhora a cobertura de `evt_*` a cada rodada.
- Sentimento: acumula a partir de 29/09/2026 com a coleta diária. Ainda não tem histórico para o backtest.
- CVM: 24 tickers pequenos ou extintos seguem sem CNPJ (ver alerta do `coletar.py`). Para resolver, acrescente-os em `config/cnpj_manual.csv`, com a fonte.
- Tamanho do banco: medir o que ocupa espaço antes da etapa 8. Depois da ampliação ficou em ~640 MB, acima do limite gratuito comum de 512 MB.

**Etapa 4 — ranking**
- 🟢 Alvo: retorno total dos próximos 21 pregões menos a mediana do universo no mesmo dia (ranking cross-section). Os 5 pregões entram como análise de sensibilidade.
- 🟢 Features: todos os sinais, ranqueados em percentil dentro do universo de cada dia. Isso tira a escala e reduz outliers; faltante vira NaN, que o LightGBM trata.
- 🟢 Baselines: aleatório, momentum (`ret_63d`), valor (`fund_lp`) e sentimento (quando houver histórico).
- 🟢 Validação walk-forward anual, com gap de 21 pregões. Métricas: IC de Spearman por dia (média, desvio, % de dias positivos) e retorno do top decil menos o bottom decil.
- 🟢 LightGBM com hiperparâmetros modestos e sem busca exaustiva. Registrar o número de variações testadas. SHAP para interpretar.
- Tabela `ranking` (ticker, data, score, posição, versão do modelo) e `scripts/gerar_ranking.py`.
- Resultado ruim contra os baselines é resultado válido e deve ser relatado com honestidade.

**Etapa 5 — backtest e paper trading**
- 🙋 Regra da carteira (N ações, pesos, frequência de rebalanceamento), fixada **antes** de ver os resultados.
- 🟢 Custos: emolumentos da B3 (~0,03%) + spread/slippage por faixa de liquidez, parametrizados em config.
- Backtest com e sem o sinal de eventos (risco de look-ahead do LLM) e separado por faixa de liquidez (as pouco negociadas enganam).
- O paper trading precisa de semanas de calendário antes de qualquer conclusão.

**Etapa 6 — relatório diário e agendamento contínuo (regra 15)**
- 🙋 Fonte de cotação intradiária: grátis com ~15 min de atraso ou paga. Trazer opções, custos e termos.
- 🟢 LLM do relatório: Gemini grátis. Checagem automática de que todo número do texto confere com os dados.
- Agendador contínuo: ciclo de ~15 min no pregão (cotação, notícias, sinais e score provisórios) e pipeline completo depois do arquivo da B3 (~21h).

**Etapa 7 — interface (regra 15: sempre atualizada)**
- API FastAPI com `atualizado_em` em cada resposta.
- React com telas que se atualizam sozinhas: mercado, ranking, detalhe da ação ao vivo, relatório, carteira e chat. Selo de provisório no que é intradiário.
- 🙋 Extrato de exemplo da XP (pode ser anonimizado). Antes, verificar se a XP tem API oficial.
- 🟢 Chat de IA com Gemini, com contexto montado pelo backend.
- Instalar Node.js na máquina.

**Etapa 8 — deploy**
- 🙋 Hospedagem de backend, banco e frontend (apresentar opções, regra 13). O usuário cria as contas.
- Banco hoje com ~2 milhões de linhas: medir depois do enxugamento e comparar com os limites gratuitos.
- Sentimento na nuvem: o torch (~1 GB) pode não caber; alternativa é o Gemini.
- Agendamentos na nuvem (ex.: GitHub Actions) e `.exe` com Electron.

## Stack
- Python 3.11+
- SQLite local (etapas 1–6) → migrar para PostgreSQL gratuito em nuvem na etapa 8
- pandas, requests, python-dotenv, pytest
- Backend da interface: FastAPI (serve a web e o desktop com a mesma API)
- Frontend: React + Recharts (dashboards) + Tailwind CSS
- Desktop: Electron empacotando o frontend React (gera .exe no Windows)
- Demais dependências são definidas em cada etapa

## Estrutura de pastas (alvo)
```
.
├── CLAUDE.md
├── etapas/            # especificação de cada etapa
├── config/            # settings.py, lista de ativos
├── src/
│   ├── db/            # schema, conexão, migrações
│   ├── coleta/        # um módulo por fonte de dados
│   ├── sinais/        # técnicos, fundamentalistas, sentimento, LLM
│   ├── ranking/       # features e modelo
│   ├── validacao/     # backtest e paper trading
│   ├── relatorio/     # geração do relatório diário
│   └── api/           # FastAPI: endpoints usados pela interface web e desktop
├── frontend/          # React app (dashboard, chat, carteira)
│   ├── src/
│   └── electron/      # wrapper Electron para gerar .exe
├── scripts/           # pontos de entrada (rodar coleta, gerar ranking...)
├── tests/
├── data/              # banco SQLite (fora do git)
├── .env               # chaves de API e credenciais (fora do git)
└── .env.example
```

## Regras que valem para TODAS as etapas
1. **Timestamp de disponibilidade**: todo dado salvo guarda `disponivel_em` = quando a informação ficou pública. Nenhum cálculo ou modelo pode usar dado com `disponivel_em` posterior à data analisada. Isso evita look-ahead bias.
2. **Contas são feitas em código, nunca pelo LLM.** O LLM extrai e interpreta texto; indicadores e números são calculados em Python.
3. **Segredos em `.env`**, nunca no código. Manter `.env.example` atualizado sem valores reais.
4. **APIs**: verifique a documentação atual antes de usar (limites e endpoints mudam). Trate rate limit com retry e backoff. Respeite termos de uso; sem scraping não autorizado.
5. **Coleta incremental**: nunca baixar tudo de novo se já existe no banco.
6. **Logging** em vez de `print` nos módulos. Erros de uma fonte não podem derrubar as outras.
7. **Testes** com pytest para cada módulo; APIs externas são mockadas nos testes.
8. **Código simples primeiro.** Não adicione complexidade (async, filas, microserviços) sem necessidade demonstrada.
9. Funções e variáveis podem ser em português ou inglês, mas mantenha consistência dentro do projeto.

## Regras adicionais (etapas 7 e 8)
10. **A API FastAPI é a única fonte de dados do frontend.** O React nunca acessa o banco diretamente.
11. **Carteira do usuário**: dados inseridos à mão ficam no banco local. Integração com XP (se viável via API oficial ou exportação de extrato) é tratada como fonte adicional, nunca obrigatória. Nunca armazenar senhas da corretora; usar apenas tokens/OAuth se a XP disponibilizar.
12. **Chat de IA**: o LLM recebe contexto montado pelo backend (ranking, sinais, carteira do usuário, relatório do dia) e responde perguntas. Não tem acesso direto ao banco; o backend é quem prepara o contexto.
13. **Deploy**: antes de implementar, o Claude deve apresentar as opções gratuitas de hospedagem (backend, banco e frontend) com prós, contras e instruções de credenciais, e esperar escolha do usuário.
14. **Segredos de produção** (URLs do banco em nuvem, chaves de deploy) ficam em `.env` e nunca no código ou no repositório.
15. **Sempre atualizado, sem ação do usuário** (requisito do usuário, 30/09/2026). O app e o site nunca são estáticos: mostram cotação, estatísticas, sinais e score do ativo **no momento**, atualizados sozinhos.
    - Coleta e cálculo rodam agendados na nuvem, não dependem do PC do usuário ligado.
    - Durante o pregão há atualização intradiária, com a frequência que a fonte gratuita permitir (cotação gratuita costuma ter ~15 min de atraso). Os valores intradiários aparecem marcados como **provisórios**. Depois do fechamento, os dados oficiais da B3 os substituem.
    - A interface se atualiza sozinha (polling ou SSE), mostrando "atualizado às HH:MM" e se o mercado está aberto ou fechado.
    - Se uma fonte falhar, a tela mostra o último dado válido com a hora dele. Nunca mostra um dado velho como se fosse atual.

## Comandos
(preencher conforme o projeto evolui)
- Ambiente: `python -m venv .venv` e depois `.venv\Scripts\activate`
- Instalar backend: `pip install -r requirements.txt`
- Instalar frontend: `cd frontend && npm install`
- Criar/atualizar banco (idempotente): `python scripts/init_db.py` — schema documentado em `docs/schema.md`
- Coletar dados (incremental; 1ª vez = 5 anos): `python scripts/coletar.py` — `--fonte cvm|b3|proventos|bcb|rss`, `--desde AAAA-MM-DD`
- Gerar sinais + relatório de cobertura: `python scripts/gerar_sinais.py` — catálogo em `docs/sinais.md`
- Medir qualidade do sentimento: `python scripts/avaliar_sentimento.py` (rótulos em `rotulos/`)
- Testes: `pytest`
- Dev local (backend): `uvicorn src.api.main:app --reload`
- Dev local (frontend): `cd frontend && npm run dev`
- Build desktop (.exe): `cd frontend && npm run build && npm run electron:build`
