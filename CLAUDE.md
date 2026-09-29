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

## Etapas
| # | Etapa | Arquivo | Status |
|---|-------|---------|--------|
| 1 | Fundação e banco de dados | [etapas/etapa1.md](etapas/etapa1.md) | ✅ concluída |
| 2 | Coleta de dados | [etapas/etapa2.md](etapas/etapa2.md) | ✅ concluída |
| 3 | Extração de sinais | [etapas/etapa3.md](etapas/etapa3.md) | ⏳ pendente |
| 4 | Modelo de ranking | [etapas/etapa4.md](etapas/etapa4.md) | ⏳ pendente |
| 5 | Backtest e paper trading | [etapas/etapa5.md](etapas/etapa5.md) | ⏳ pendente |
| 6 | Relatório diário | [etapas/etapa6.md](etapas/etapa6.md) | ⏳ pendente |
| 7 | Interface (dashboard + chat IA + carteira) | [etapas/etapa7.md](etapas/etapa7.md) | ⏳ pendente |
| 8 | Deploy (desktop .exe + web gratuito) | [etapas/etapa8.md](etapas/etapa8.md) | ⏳ pendente |

Status possíveis: ⏳ pendente · 🔨 em andamento · ✅ concluída

## Configuração do usuário
- Ativos: lista editável em `config/ativos.csv` (20 ações: os 5 do exemplo + maiores da B3; BOVA11 como benchmark). Para adicionar, incluir linha (com `apelidos` para busca em notícias) e rodar `python scripts/coletar.py`. Feeds de notícias em `config/feeds.csv`.
- Hardware: 16 GB RAM, GPU Intel UHD integrada (sem CUDA), ~200 GB livres. Sem GPU: sentimento com modelo pronto em CPU ou LLM via API; fine-tuning local inviável.
- Experiência: intermediário
- Python: 3.13, ambiente virtual em `.venv`
- Repositório: https://github.com/fel1x-Hub/projeto_b3 (branch `main`, commits regulares por passo)

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

## Comandos
(preencher conforme o projeto evolui)
- Ambiente: `python -m venv .venv` e depois `.venv\Scripts\activate`
- Instalar backend: `pip install -r requirements.txt`
- Instalar frontend: `cd frontend && npm install`
- Criar/atualizar banco (idempotente): `python scripts/init_db.py` — schema documentado em `docs/schema.md`
- Coletar dados (incremental; 1ª vez = 5 anos): `python scripts/coletar.py` — `--fonte cvm|b3|proventos|bcb|rss`, `--desde AAAA-MM-DD`
- Testes: `pytest`
- Dev local (backend): `uvicorn src.api.main:app --reload`
- Dev local (frontend): `cd frontend && npm run dev`
- Build desktop (.exe): `cd frontend && npm run build && npm run electron:build`
