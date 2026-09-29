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
pytest
```

Ativos acompanhados: [config/ativos.csv](config/ativos.csv). Schema do banco: [docs/schema.md](docs/schema.md).
