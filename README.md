# projeto_b3

Sistema pessoal de apoio à análise da bolsa brasileira (B3): coleta dados, extrai sinais, gera um ranking diário de ativos e um relatório explicando o porquê. É ferramenta de apoio à decisão — não envia ordens.

Especificação e status das etapas em [CLAUDE.md](CLAUDE.md).

## Começando

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env            # ajuste se quiser
python scripts/init_db.py         # cria data/b3.db
python scripts/coletar.py         # baixa 5 anos de dados (depois, só o que faltar)
python scripts/extrair_eventos.py # eventos de fatos relevantes com Gemini (precisa de GEMINI_API_KEY no .env)
python scripts/gerar_sinais.py    # calcula os sinais e mostra a cobertura
pytest
```

Rotina diária sugerida: `coletar.py`, depois `extrair_eventos.py`, depois `gerar_sinais.py`.

Ativos acompanhados: [config/ativos.csv](config/ativos.csv). Feeds de notícias: [config/feeds.csv](config/feeds.csv). Schema do banco: [docs/schema.md](docs/schema.md). Catálogo de sinais: [docs/sinais.md](docs/sinais.md).
