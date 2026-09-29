# Etapa 1 — Fundação e banco de dados

## Objetivo
Criar a estrutura do projeto, a configuração central e o schema do banco SQLite que todas as outras etapas vão usar.

## Tarefas
1. Criar a estrutura de pastas definida no CLAUDE.md, com `__init__.py` onde necessário.
2. `requirements.txt` inicial, `.gitignore` (incluindo `.env`, `data/`, `__pycache__`), `.env.example`.
3. `config/settings.py`: carrega `.env`, define caminho do banco, lista de ativos, níveis de log.
4. `src/db/`: conexão SQLite, criação do schema, função de migração simples (versão do schema numa tabela).
5. Schema inicial (propor e justificar antes de criar), cobrindo no mínimo:
   - `ativos` (ticker, nome, setor, ativo sim/não)
   - `cotacoes` (ticker, data, abertura, máxima, mínima, fechamento, volume, fonte, `disponivel_em`, `coletado_em`)
   - `macro` (serie, data, valor, fonte, `disponivel_em`, `coletado_em`)
   - `noticias` (id, titulo, resumo, url, fonte, publicado_em, `disponivel_em`, `coletado_em`, hash para deduplicação)
   - `noticias_ativos` (relação notícia ↔ ticker)
   - `documentos` (tipo, ticker, data referência, url, conteúdo ou caminho, `disponivel_em`, `coletado_em`)
   - `execucoes_coleta` (fonte, início, fim, status, registros novos, erro)
   - Chaves únicas que impeçam duplicatas.
6. Configuração de logging.
7. Testes: criação do banco do zero, idempotência (rodar duas vezes não quebra nem duplica), inserção e leitura básica.

## Fora do escopo
Qualquer chamada a API externa.

## Critério de pronto
- `python scripts/init_db.py` cria o banco do zero sem erros e pode ser rodado de novo sem problemas.
- `pytest` passa.
- Schema documentado (comentários no código ou `docs/schema.md`).
