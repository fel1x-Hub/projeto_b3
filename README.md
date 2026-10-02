# projeto_b3

Sistema pessoal de apoio à análise da bolsa brasileira (B3). Ele coleta dados de toda a bolsa (ações e units com volume médio ≥ R$ 100 mil/dia), calcula sinais técnicos, fundamentalistas, de notícias e de fatos relevantes, e gera um ranking diário. Também produz um relatório explicando o porquê, valida o método (backtest e paper trading) e se atualiza sozinho.

**É ferramenta de apoio à decisão: não envia ordens e não é recomendação de investimento.**

Especificação, status das etapas e regras do projeto estão em [CLAUDE.md](CLAUDE.md).

## Instalação

Requer Python 3.11+ (desenvolvido no 3.13) e ~3 GB livres (banco + cache dos arquivos da B3/CVM).

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt   # inclui torch CPU (FinBERT) e LightGBM
copy .env.example .env            # Linux/Mac: cp
python scripts/init_db.py         # cria data/b3.db
```

## Configuração (`.env`)

| Variável | Para quê |
|---|---|
| `GEMINI_API_KEY` | Chave gratuita do Google AI Studio (aistudio.google.com). Usada para extrair eventos de fatos relevantes e redigir o relatório. Sem ela, o resto funciona e esses dois passos são pulados/falham isolados. |
| `GEMINI_MODELO` | Padrão `gemini-3.5-flash-lite` (maior cota gratuita). |
| `HISTORICO_ANOS` | Anos de histórico na primeira carga (padrão 5). |
| `DB_PATH`, `LOG_DIR`, `RAW_DIR`, `LOG_LEVEL` | Caminhos e nível de log (padrões funcionam). |

As chaves ficam só no `.env`, que está fora do git. Nunca coloque chaves no `.env.example`.

Outros arquivos de configuração:
- [config/ativos.csv](config/ativos.csv): ativos forçados no universo mesmo abaixo do corte de liquidez, apelidos para a busca de notícias e o benchmark BOVA11. O resto do universo é detectado sozinho.
- [config/feeds.csv](config/feeds.csv): feeds RSS de notícias.
- [config/eventos_manuais.csv](config/eventos_manuais.csv) e [config/cnpj_manual.csv](config/cnpj_manual.csv): correções manuais, sempre com referência da fonte.

## Primeira carga

```bash
python scripts/coletar.py                 # 5 anos de cotações, proventos, macro, CVM e notícias (~1 h)
python scripts/extrair_eventos.py         # eventos via Gemini (a cota gratuita diária esgota; continue nos dias seguintes)
python scripts/gerar_sinais.py            # universo + todos os sinais (~40 min na primeira vez)
python scripts/gerar_ranking.py           # ranking do último pregão
python scripts/paper_trading.py           # inicia/atualiza a carteira simulada
python scripts/gerar_relatorio.py         # relatorios/AAAA-MM-DD.md
```

Todos os scripts são incrementais: rodar de novo só busca/calcula o que falta.

## Uso diário: um comando

```bash
python scripts/rodar_diario.py
```

Ele encadeia coleta → eventos → sinais → ranking → paper trading → relatório. Cada passo roda isolado: se um falha, os seguintes rodam com os dados que houver, e o resumo final mostra o que falhou (detalhes em `logs/app.log`). Rode depois das ~21h, quando a B3 publica o arquivo do dia.

Durante o pregão, `python scripts/ciclo_intradiario.py` atualiza a cotação do momento (yfinance, ~15 min de atraso), as notícias e um ranking **provisório** (`lgbm-v1-provisorio`), que não substitui o oficial.

## Atualização automática (agendador)

`scripts/agendador.py` fica rodando e faz sozinho:
- durante o pregão (dias úteis, 10h–18h de Brasília): ciclo intradiário a cada 15 min;
- dias úteis às 21h30: o pipeline diário completo.

O estado fica em `data/agendador_estado.json`, então reiniciar não repete o que já rodou.

**Windows (Agendador de Tarefas), inicia sozinho ao entrar no Windows, sem janela e sem administrador:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\instalar_agendador.ps1          # instala e inicia
powershell -ExecutionPolicy Bypass -File scripts\instalar_agendador.ps1 -Remover # remove
Get-ScheduledTask -TaskName ProjetoB3-Agendador                                  # confere
```

**Linux/Mac (cron):** inicie o agendador no boot com `@reboot cd /caminho/projeto_b3 && .venv/bin/python scripts/agendador.py >> logs/agendador.out 2>&1`. Outra opção é agendar só o diário com `30 21 * * 1-5 cd /caminho/projeto_b3 && .venv/bin/python scripts/rodar_diario.py`.

O agendador local só roda com o PC ligado. Na etapa 8 esse papel passa para a nuvem.

## App desktop e API

```bash
python desktop/main.py                                              # abre o app (sobe a API embutida se preciso)
powershell -ExecutionPolicy Bypass -File scripts\criar_atalho.ps1   # atalho "Projeto B3" na Área de Trabalho
uvicorn src.api.main:app --host 127.0.0.1                           # só a API; Swagger em http://127.0.0.1:8000/docs
```

O app tem as abas Mercado, Ranking, Ação, Carteira, Relatório e Chat IA. Ele se atualiza sozinho: a cada 1 min com o pregão aberto e a cada 5 min com ele fechado. A barra de baixo mostra se o pregão está aberto, a hora do dado e o selo **PROVISÓRIO** nos valores intradiários. Se a API falhar, a tela mantém o último dado válido e avisa.

A API exige `API_TOKEN` no `.env`. Os endpoints estão documentados em [docs/api.md](docs/api.md).

### Carteira

Há três formas de informar a carteira. Todas podem ser usadas juntas:
1. **Nova operação**: compra ou venda manual.
2. **Importar extrato…**: no site da B3, entre na Área do Investidor (investidor.b3.com.br), vá em Extratos → Negociação, filtre o período e exporte. Funciona para a XP e qualquer corretora. Também aceita uma planilha simples com ticker, tipo, data, quantidade e preço. Reimportar não duplica, e as linhas não reconhecidas são listadas.
3. **Sincronizar XP** (Meu Pluggy / Open Finance, grátis para uso pessoal): o passo a passo está em [src/coleta/pluggy.py](src/coleta/pluggy.py). Você autoriza no app da XP, e nenhuma senha passa pelo sistema. As credenciais `PLUGGY_*` ficam no `.env`. A sincronização roda junto com a coleta diária.

O ganho "ao vivo" é a quantidade × a cotação do momento (~15 min de atraso). As indicações seguem a regra do sistema:
- **comprar:** papéis do top 30 que não estão na carteira;
- **observar:** papéis da carteira entre as posições 31 e 60;
- **considerar vender:** papéis da carteira abaixo da posição 60.

Cada indicação mostra o "por quê" (os sinais que mais pesaram). **Não é recomendação de investimento.**

## Site (React)

Precisa de Node.js 20+. Sem acesso de administrador, use a versão portátil: baixe o `.zip` "Windows x64" em nodejs.org/en/download, extraia em `%LOCALAPPDATA%
ode` e coloque essa pasta no PATH do seu usuário. Feito isso:

```bash
uvicorn src.api.main:app --host 127.0.0.1     # a API (ou deixe o app desktop aberto, que já a sobe)
cd frontend && npm install && npm run dev     # abre em http://127.0.0.1:5173
cd frontend && npm test                       # testes dos componentes
```

Na primeira vez, o site pede o `API_TOKEN` do `.env`, que fica guardado só naquele navegador. As telas e a atualização automática são as mesmas do app desktop, e as duas interfaces leem a mesma API.

## Na nuvem (grátis)

O passo a passo para colocar tudo online está em [DEPLOY.md](DEPLOY.md):
- o pipeline roda no GitHub Actions;
- os dados das telas e a carteira ficam no Neon;
- a API fica no Render e o site no Vercel;
- o app desktop (`ProjetoB3.exe`) sai em Releases.

Depois disso nada depende do seu PC ligado.

## Relatório diário

Fica em `relatorios/AAAA-MM-DD.md`. Os números são todos calculados em código ([src/relatorio/insumos.py](src/relatorio/insumos.py)), e o Gemini só redige o texto. Uma checagem automática confere cada número do texto contra os insumos. Se o relatório citar número sem origem, é refeito uma vez; se persistir, vai para `relatorios/rejeitados/` e não é publicado. Os insumos de cada dia ficam em `relatorios/insumos/` para auditoria.

## Outros comandos

| Comando | O que faz |
|---|---|
| `pytest` | Testes (APIs externas mockadas) |
| `python scripts/coletar.py --fonte b3` | Uma fonte só (`cvm`, `b3`, `proventos`, `bcb`, `rss`) |
| `python scripts/gerar_sinais.py --familia tecnicos --desde 2026-09-01` | Uma família de sinais, regravando só a partir de uma data |
| `python scripts/gerar_relatorio.py --ultimos 5` | Relatórios dos últimos 5 pregões |
| `python scripts/avaliar_ranking.py` | Walk-forward do modelo (IC, spread por decil) |
| `python scripts/backtest.py` | Backtest da regra top 30 com custos |
| `python scripts/avaliar_sentimento.py` | Métricas do FinBERT contra os rótulos |

## Documentação

- [docs/schema.md](docs/schema.md): banco de dados e regra `disponivel_em` (sem look-ahead)
- [docs/sinais.md](docs/sinais.md): catálogo de sinais
- [docs/ranking.md](docs/ranking.md) e [docs/ranking_avaliacao.md](docs/ranking_avaliacao.md): modelo e avaliação
- [docs/backtest.md](docs/backtest.md) e [docs/validacao.md](docs/validacao.md): backtest e paper trading
- [docs/sentimento_avaliacao.md](docs/sentimento_avaliacao.md): avaliação do sentimento
