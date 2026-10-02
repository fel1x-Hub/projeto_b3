import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api import assistente, main
from src.db import nuvem
from src.db.conexao import conectar
from src.db.migracoes import migrar

TS = "2026-09-29T22:00:00+00:00"
TOKEN = "token-de-teste"
H = {"Authorization": f"Bearer {TOKEN}"}


def _popular(conn):
    hoje = date.today()
    dias = [(hoje - timedelta(days=k)).isoformat() for k in (3, 2, 1)]
    with conn:
        for t, nome in (("PETR4", "Petrobras"), ("VALE3", "Vale"), ("BOVA11", "iShares Ibovespa")):
            conn.execute("INSERT INTO ativos (ticker, nome, codigo_cvm, ativo, criado_em, atualizado_em) "
                         "VALUES (?, ?, ?, 1, ?, ?)", (t, nome, {"PETR4": "9512"}.get(t), TS, TS))
        for i, d in enumerate(dias):
            for t, base in (("PETR4", 30.0), ("VALE3", 60.0), ("BOVA11", 150.0)):
                conn.execute("INSERT INTO cotacoes (ticker, data, fechamento, volume, fonte, disponivel_em, coletado_em) "
                             "VALUES (?, ?, ?, 1000, 'b3_cotahist', ?, ?)", (t, d, base + i, TS, TS))
        ult = dias[-1]
        for t, pos, score in (("PETR4", 1, 0.6), ("VALE3", 2, 0.4)):
            conn.execute("INSERT INTO ranking VALUES (?, ?, ?, ?, 'lgbm-v1', ?, ?)", (ult, t, score, pos, TS, TS))
            conn.execute("INSERT INTO universo VALUES (?, ?, 1e6, 'liquidez', ?)", (ult, t, TS))
            conn.execute("INSERT INTO ranking_fatores VALUES (?, ?, 'lgbm-v1', 'fund_lp', 0.9, ?)",
                         (ult, t, 0.02 if t == "PETR4" else -0.01))
            conn.execute("INSERT INTO sinais (ticker, data, nome, valor, versao, disponivel_em, calculado_em) "
                         "VALUES (?, ?, 'fund_lp', ?, 1, ?, ?)", (t, ult, 0.15 if t == "PETR4" else 0.05, TS, TS))
        conn.execute("INSERT INTO macro (serie, data, valor, fonte, disponivel_em, coletado_em) "
                     "VALUES ('selic_meta', ?, 13.75, 'bcb', ?, ?)", (ult, TS, TS))
        conn.execute("INSERT INTO relatorios VALUES ('2026-09-29', '# Relatório\nTexto.', ?)", (TS,))
        # tipo gravado pela coleta da CVM é 'fato_relevante' (não o nome da categoria)
        conn.execute("INSERT INTO documentos (id, tipo, ticker, assunto, url, fonte, id_externo, disponivel_em, coletado_em) "
                     "VALUES (1, 'fato_relevante', 'PETR4', 'Dividendos', 'http://x', 'cvm_ipe', 'a', ?, ?)", (TS, TS))
        conn.execute("INSERT INTO eventos_documentos VALUES (1, 'm', 1, 'dividendos', 'positiva', 3, 'Paga dividendos', ?)",
                     (TS,))


def _preparar_postgres(url: str, sqlite_path) -> None:
    """Postgres de teste zerado e preenchido pelo mesmo publicador usado em produção."""
    import psycopg

    from scripts import publicar_nuvem
    with psycopg.connect(url, autocommit=True) as pg:
        pg.execute("DROP SCHEMA public CASCADE")
        pg.execute("CREATE SCHEMA public")
    sq = conectar(sqlite_path)
    try:
        publicar_nuvem.publicar(sq, url, completo=True)
    finally:
        sq.close()


# SQLite sempre; Postgres quando houver TEST_DATABASE_URL (ex.: Postgres portátil local)
BACKENDS = ["sqlite"] + (["postgres"] if os.getenv("TEST_DATABASE_URL") else [])


@pytest.fixture(params=BACKENDS)
def cliente(request, tmp_path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    monkeypatch.setattr(main, "limitador", main.Limitador(dict(main.limitador.limites)))   # zerado a cada teste
    caminho = tmp_path / "api.db"
    conn = conectar(caminho)
    migrar(conn)
    _popular(conn)
    conn.close()
    if request.param == "postgres":
        url = os.environ["TEST_DATABASE_URL"]
        _preparar_postgres(url, caminho)
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setattr(main.app.state, "db_path", None)
        nuvem.fechar_pool()
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(main.app.state, "db_path", caminho)
    with TestClient(main.app) as c:
        yield c
    nuvem.fechar_pool()


def _conn():
    """Conexão direta ao banco que a API do teste está usando (nunca o data/b3.db real)."""
    assert main.app.state.db_path is not None or os.getenv("DATABASE_URL")
    return nuvem.conectar_api(main.app.state.db_path)


def test_mercado_publico_e_parte_pessoal_exige_login(cliente):
    assert cliente.get("/saude").json()["ok"] is True
    for publico in ("/mercado", "/ranking", "/ativo/PETR4", "/relatorio/ultimo", "/status"):
        assert cliente.get(publico).status_code == 200, publico
    for pessoal in ("/carteira", "/notificacoes", "/ativo/PETR4/porque"):
        assert cliente.get(pessoal).status_code == 401, pessoal
        assert cliente.get(pessoal, headers={"Authorization": "Bearer errado"}).status_code == 401
    assert cliente.post("/chat", json={"mensagens": [{"papel": "usuario", "texto": "oi"}]}).status_code == 401


def test_envelope_e_ranking(cliente):
    r = cliente.get("/ranking", headers=H).json()
    assert set(r) == {"atualizado_em", "provisorio", "mercado_aberto", "dados"}
    linhas = r["dados"]["linhas"]
    assert [l["ticker"] for l in linhas] == ["PETR4", "VALE3"] and linhas[0]["preco"] == 32.0
    assert r["provisorio"] is False and r["atualizado_em"] == TS


def test_cotacao_do_momento_e_ranking_provisorio_prevalecem(cliente):
    conn = _conn()
    agora = "2099-01-01T15:00:00+00:00"  # mais novo que qualquer fechamento oficial
    with conn:
        conn.execute("INSERT INTO cotacao_atual VALUES ('PETR4', 33.5, 32.0, 0.046875, ?, 'yfinance_intradia', ?)",
                     (agora, agora))
        conn.execute("INSERT INTO ranking VALUES ('2099-01-01', 'VALE3', 0.7, 1, 'lgbm-v1-provisorio', ?, ?)", (agora, agora))
    conn.close()
    r = cliente.get("/ranking", headers=H).json()
    assert r["provisorio"] is True and r["dados"]["linhas"][0]["ticker"] == "VALE3"
    assert cliente.get("/ranking?versao=oficial", headers=H).json()["provisorio"] is False
    a = cliente.get("/ativo/petr4", headers=H).json()
    assert a["dados"]["cotacao"] == {"preco": 33.5, "variacao_dia": 0.046875, "horario": agora, "provisorio": True}


def test_ativo_e_404(cliente):
    a = cliente.get("/ativo/PETR4", headers=H).json()["dados"]
    assert a["ranking"]["posicao"] == 1 and len(a["precos"]) == 3
    assert a["sinais"]["sinais"][0]["percentil"] == 1.0
    assert a["fatores"][0]["texto"].startswith("lucro/preço muito alto")
    assert cliente.get("/ativo/XPTO3", headers=H).status_code == 404


def test_carteira_operacao_manual_e_rendimento(cliente):
    ontem = (date.today() - timedelta(days=3)).isoformat()
    r = cliente.post("/carteira/operacao", headers=H,
                     json={"ticker": "petr4", "tipo": "compra", "data": ontem, "quantidade": 100, "preco": 30, "custos": 10})
    assert r.status_code == 201
    c = cliente.get("/carteira", headers=H).json()["dados"]
    p = c["posicoes"][0]
    assert p["ticker"] == "PETR4" and p["valor"] == 3200.0 and p["custo"] == 3010.0
    assert p["ganho"] == pytest.approx(190.0) and p["leitura"] == "manter"
    ind = cliente.get("/carteira/indicacoes", headers=H).json()["dados"]
    assert [x["ticker"] for x in ind["comprar"]] == ["VALE3"]          # top 30 fora da carteira
    assert "Não é recomendação" in ind["aviso"]
    assert cliente.get("/carteira/evolucao", headers=H).json()["dados"][-1]["valor"] == 3200.0
    futuro = (date.today() + timedelta(days=2)).isoformat()
    assert cliente.post("/carteira/operacao", headers=H, json={"ticker": "PETR4", "tipo": "compra", "data": futuro,
                                                               "quantidade": 1, "preco": 1}).status_code == 422
    op_id = cliente.get("/carteira/operacoes", headers=H).json()["dados"][0]["id"]
    assert cliente.delete(f"/carteira/operacao/{op_id}", headers=H).json() == {"apagadas": 1}


def test_importar_extrato(cliente):
    from pathlib import Path
    exemplo = Path(__file__).parent / "dados" / "extrato_b3_exemplo.csv"
    r = cliente.post("/carteira/importar", headers=H, files={"arquivo": (exemplo.name, exemplo.read_bytes(), "text/csv")})
    assert r.status_code == 200 and r.json()["importadas"] == 4 and len(r.json()["nao_reconhecidas"]) == 2
    tickers = {p["ticker"] for p in cliente.get("/carteira", headers=H).json()["dados"]["posicoes"]}
    assert tickers == {"PETR4", "WEGE3"}
    ruim = cliente.post("/carteira/importar", headers=H, files={"arquivo": ("x.csv", b"a;b\n1;2\n", "text/csv")})
    assert ruim.status_code == 422 and "colunas não encontradas" in ruim.json()["detail"]


def test_sincronizar_sem_pluggy_explica(cliente, monkeypatch):
    monkeypatch.delenv("PLUGGY_CLIENT_ID", raising=False)
    r = cliente.post("/carteira/sincronizar", headers=H)
    assert r.status_code == 409 and "PLUGGY_CLIENT_ID" in r.json()["detail"]


def test_relatorio(cliente):
    r = cliente.get("/relatorio/ultimo", headers=H).json()["dados"]
    assert r["data"] == "2026-09-29" and r["markdown"].startswith("# Relatório")
    assert cliente.get("/relatorio/2020-01-01", headers=H).status_code == 404


class LLM:
    def __init__(self, *respostas):
        self.respostas, self.prompts = list(respostas), []

    def classificar(self, prompt, schema=None):
        self.prompts.append(prompt)
        return self.respostas.pop(0)


def test_chat_contexto_e_checagem(cliente, monkeypatch):
    llm = LLM("A PETR4 subiu 50%.", "A PETR4 está em 1º lugar no ranking, com score 0,600.")
    monkeypatch.setattr(assistente, "_cliente_padrao", lambda: llm)
    r = cliente.post("/chat", headers=H, json={"mensagens": [{"papel": "usuario", "texto": "Como está a petr4?"}]})
    d = r.json()["dados"]
    assert d["ativos_citados"] == ["PETR4"] and d["numeros_nao_verificados"] == []
    assert "50%" in llm.prompts[1] and '"ticker": "PETR4"' in llm.prompts[0]
    assert "Não é recomendação" in d["aviso"]


def test_chat_llm_fora_do_ar_da_503(cliente, monkeypatch):
    def quebra():
        raise RuntimeError("GEMINI_API_KEY ausente")
    monkeypatch.setattr(assistente, "_cliente_padrao", quebra)
    r = cliente.post("/chat", headers=H, json={"mensagens": [{"papel": "usuario", "texto": "oi"}]})
    assert r.status_code == 503


def test_porque(cliente, monkeypatch):
    llm = LLM("O lucro/preço muito alto (percentil 90 do universo) favorece a PETR4.")
    monkeypatch.setattr(assistente, "_cliente_padrao", lambda: llm)
    assistente._cache_porque.clear()
    d = cliente.get("/ativo/PETR4/porque", headers=H).json()["dados"]
    assert d["numeros_nao_verificados"] == [] and d["dados"]["posicao"] == 1
    assert cliente.get("/ativo/BOVA11/porque", headers=H).status_code == 404


def test_notificacoes_e_status(cliente):
    assert cliente.get("/notificacoes", headers=H).status_code == 200
    s = cliente.get("/status", headers=H).json()["dados"]
    assert s["ultimo_relatorio"] == "2026-09-29" and s["ranking_oficial"]["versao"] == "lgbm-v1"


def test_ibovespa_do_momento_so_se_for_do_dia(cliente):
    conn = _conn()
    velho, novo = "2000-01-03T17:00:00+00:00", "2099-01-02T17:00:00+00:00"
    with conn:
        conn.execute("INSERT INTO cotacao_atual VALUES ('IBOV', 100000, 99000, 0.0101, ?, 'yfinance_intradia', ?)",
                     (velho, velho))
    assert cliente.get("/mercado", headers=H).json()["dados"]["ibovespa"]["nome"] == "BOVA11"   # dia já fechado
    with conn:
        conn.execute("UPDATE cotacao_atual SET horario_cotacao = ?, coletado_em = ?", (novo, novo))
    conn.close()
    assert cliente.get("/mercado", headers=H).json()["dados"]["ibovespa"]["nome"] == "Ibovespa"


def test_health_e_limitador():
    assert main.Limitador({"geral": 2, "llm": 1}).permitir("ip", "llm", 0.0)
    lim = main.Limitador({"geral": 2, "llm": 1})
    assert [lim.permitir("ip", "geral", t) for t in (0.0, 1.0, 2.0)] == [True, True, False]
    assert lim.permitir("ip", "geral", 61.5) and lim.permitir("outro", "geral", 2.0)


def test_limite_devolve_429(cliente, monkeypatch):
    monkeypatch.setattr(main, "limitador", main.Limitador({"geral": 2, "llm": 1}))
    codigos = [cliente.get("/status", headers=H).status_code for _ in range(3)]
    assert codigos == [200, 200, 429]
    assert cliente.get("/health").status_code == 200        # health nunca é limitado


def test_fatos_relevantes_aparecem_na_acao(cliente):
    fatos = cliente.get("/ativo/PETR4", headers=H).json()["dados"]["fatos_relevantes"]
    assert fatos and fatos[0]["resumo"] == "Paga dividendos" and fatos[0]["data"] == "2026-09-29"


def test_cors_aceita_so_o_site():
    import importlib
    os.environ["API_ORIGENS_REGEX"] = r"^https://projeto-b3[a-z0-9-]*\.vercel\.app$"
    try:
        m = importlib.reload(main)        # o middleware lê o ambiente ao montar o app
        c = TestClient(m.app)
        ok = c.options("/saude", headers={"Origin": "https://projeto-b3-git-main-fulano.vercel.app",
                                          "Access-Control-Request-Method": "GET"})
        assert ok.headers.get("access-control-allow-origin") == "https://projeto-b3-git-main-fulano.vercel.app"
        ruim = c.options("/saude", headers={"Origin": "https://malicioso.com", "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in ruim.headers
    finally:
        del os.environ["API_ORIGENS_REGEX"]
        importlib.reload(main)


def _criar_usuario():
    from src.api import autenticacao
    conn = _conn()
    try:
        autenticacao.gravar_usuario(conn, "Miguel Felix", "senha-de-teste", TS)
    finally:
        conn.close()


def test_login_com_usuario_e_senha(cliente):
    _criar_usuario()
    errado = cliente.post("/login", json={"usuario": "Miguel Felix", "senha": "outra"})
    assert errado.status_code == 401
    assert cliente.post("/login", json={"usuario": "ninguem", "senha": "senha-de-teste"}).status_code == 401
    r = cliente.post("/login", json={"usuario": "  miguel   FELIX ", "senha": "senha-de-teste"})   # nome normalizado
    assert r.status_code == 200 and r.json()["usuario"] == "miguel felix"
    sessao = {"Authorization": f"Bearer {r.json()['sessao']}"}
    assert cliente.get("/carteira", headers=sessao).status_code == 200
    assert cliente.get("/eu", headers=sessao).json() == {"usuario": "miguel felix", "logado": True}
    assert cliente.get("/eu").json()["logado"] is False
    conn = _conn()
    try:
        guardado = conn.execute("SELECT senha_hash FROM usuarios").fetchone()[0]
    finally:
        conn.close()
    assert "senha-de-teste" not in guardado and guardado.startswith("pbkdf2_sha256$")


def test_visitante_nao_ve_o_que_esta_na_carteira(cliente):
    cliente.post("/carteira/operacao", headers=H, json={"ticker": "PETR4", "tipo": "compra",
                 "data": (date.today() - timedelta(days=3)).isoformat(), "quantidade": 1, "preco": 30})
    assert any(l["na_carteira"] for l in cliente.get("/ranking", headers=H).json()["dados"]["linhas"])
    assert not any(l["na_carteira"] for l in cliente.get("/ranking").json()["dados"]["linhas"])


def test_login_tem_limite_de_tentativas(cliente, monkeypatch):
    monkeypatch.setattr(main, "limitador", main.Limitador({"geral": 100, "llm": 10, "login": 2}))
    codigos = [cliente.post("/login", json={"usuario": "x", "senha": "y"}).status_code for _ in range(3)]
    assert codigos == [401, 401, 429]


def test_sessao_expira_e_nao_aceita_assinatura_falsa(monkeypatch):
    from src.api import autenticacao
    monkeypatch.setenv("API_TOKEN", "segredo")
    s = autenticacao.emitir_sessao("Miguel Felix", agora=1000.0, dias=1)
    assert autenticacao.validar_sessao(s, agora=1000.0 + 3600) == "miguel felix"
    assert autenticacao.validar_sessao(s, agora=1000.0 + 2 * 86400) is None
    versao, corpo, _ = s.split(".")
    assert autenticacao.validar_sessao(f"{versao}.{corpo}.assinaturafalsa", agora=1000.0) is None
    monkeypatch.setenv("API_TOKEN", "outro")          # trocar o segredo derruba as sessões
    assert autenticacao.validar_sessao(s, agora=1000.0) is None
