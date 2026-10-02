# API (etapa 7)

API FastAPI local (`uvicorn src.api.main:app`), **única fonte de dados** do app desktop (Qt) e do site (React) (regra 10). O Swagger fica em `/docs`.

## Convenções

- **Autenticação:** `Authorization: Bearer <API_TOKEN>`, com o token no `.env`. Sem token configurado, a API não sobe. Só `/saude` dispensa o token.
- **Envelope:** toda resposta tem a forma abaixo (regra 15).

  ```json
  {"atualizado_em": "2026-10-01T17:31:36+00:00", "provisorio": true, "mercado_aberto": false, "dados": {...}}
  ```

  - `atualizado_em` é quando o dado mais recente daquela resposta ficou pronto, não a hora da requisição. Se uma fonte falhou, ele mostra a hora do último dado válido.
  - `provisorio` vale `true` quando há valor intradiário: cotação do momento ou ranking `lgbm-v1-provisorio`.
- **Erros:** códigos HTTP com `{"detail": "mensagem clara"}`. 404 para ticker, data ou relatório inexistente; 422 para entrada inválida; 503 se o LLM estiver indisponível.
- **Números:** a API devolve números crus (float) e as interfaces formatam. Textos de LLM só citam números que vêm dos dados (regra 2), com a mesma checagem do relatório.
- **Ranking em vigor:**
  - Durante o pregão vale o provisório de hoje, se ele existir e for mais novo que o oficial.
  - Depois do pipeline da noite, vale o oficial.
  - `?versao=oficial` força o oficial.

## Endpoints

| Método e caminho | O que devolve |
|---|---|
| `GET /saude` | `ok` e a versão da API (sem token; usado pelo app para saber se a API está no ar) |
| `GET /status` | Mercado aberto/fechado e horário de cada fonte (cotação do momento, ranking oficial e provisório, relatório, última execução de cada coleta com sucesso/falha) |
| `GET /mercado` | Cards de Ibovespa (do momento), dólar, Selic e IPCA; top 5 e bottom 5 do ranking em vigor |
| `GET /ranking?data=&versao=` | Ranking completo: posição, ticker, nome, score, preço e variação do dia, sentimento 21d, volume anormal, se está na carteira |
| `GET /ativo/{ticker}?dias=` | Cadastro, cotação do momento, histórico de preço (OHLC) e de score/posição, sinais atuais (valor + percentil + descrição), fatores do ranking, notícias com sentimento, fatos relevantes |
| `GET /ativo/{ticker}/porque` | Texto curto do LLM explicando a posição, só a partir dos fatores (cache por ticker, dia e versão do ranking) |
| `GET /relatorios` | Datas com relatório |
| `GET /relatorio/{data}` | Markdown do relatório (`ultimo` = o mais recente) |
| `GET /carteira` | Posições (quantidade, preço médio, custo, valor atual, ganho no dia e desde a compra, proventos recebidos), totais, comparação com o Ibovespa e posição de cada ação no ranking |
| `GET /carteira/evolucao` | Série diária do patrimônio da carteira e do Ibovespa na mesma base |
| `GET /carteira/indicacoes` | **Comprar**: top 30 fora da carteira. **Vender**: papéis da carteira que caíram no ranking. Cada item traz os fatores (regra 16) |
| `GET /carteira/operacoes` | Operações registradas |
| `POST /carteira/operacao` | Registra compra ou venda manual (ticker, tipo, data, quantidade, preço, custos) |
| `DELETE /carteira/operacao/{id}` | Apaga uma operação (só as manuais e as importadas) |
| `POST /carteira/importar` | Upload de CSV/XLSX (negociações da Área do Investidor da B3 ou extrato da corretora). Devolve as linhas importadas e as não reconhecidas, sem descartar o resto |
| `POST /carteira/sincronizar` | Puxa as posições da XP pelo Meu Pluggy (se as credenciais estiverem no `.env`) |
| `POST /chat` | `{"mensagens": [{"papel": "usuario", "texto": "..."}]}` → resposta do LLM, que usa o contexto montado pelo backend (regra 12) |
| `GET /notificacoes` | Alertas do dia: papel da carteira que saiu do top 30 ou entrou no fundo, fato relevante novo da carteira ou do top 30, variação forte no dia, fonte de dados com falha |

## Carteira (regra 11 e regra 16)

- **Operações** (`carteira_operacoes`): manuais ou importadas. A posição **nunca é armazenada**: ela é recalculada das operações.
  - O preço médio segue a regra da Receita, e a venda não altera o preço médio.
  - Desdobramentos e grupamentos da tabela `proventos` ajustam a quantidade e o preço.
  - Proventos recebidos = valor por ação × quantidade na data ex.
- **Sincronização XP** (`carteira_sincronizada`): é a foto das posições vinda do Meu Pluggy (Open Finance), com atualização diária pela instituição.
  - Quando existe, a quantidade vem dela.
  - O custo vem das operações, se houver, ou do valor aplicado que a XP informa.
  - Nenhuma senha é armazenada: só o Client ID e o Client Secret da Pluggy e o Item ID, todos no `.env`.
- **Ganho em tempo real:** quantidade × cotação do momento (~15 min de atraso), marcado como provisório. Depois do fechamento, usa o preço oficial da B3.
- **Indicações**, sempre com o aviso "não é recomendação":
  - **comprar:** o top 30 do ranking em vigor que não está na carteira. É a regra validada (backtest e paper trading).
  - **observar:** papel da carteira entre as posições 31 e 60.
  - **considerar vender:** papel da carteira abaixo da posição 60 (o meio do caminho evita giro desnecessário, ver docs/validacao.md).
  - **sem leitura:** papel fora do universo do modelo (ex.: FII, ETF, ilíquido).
