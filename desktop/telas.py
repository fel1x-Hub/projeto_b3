"""Abas do app: Mercado, Ranking, Ativo, Carteira, Relatório e Chat.

Cada aba recebe o cliente da API e tem `atualizar()`; a janela chama a aba
visível no timer (regra 15). Nenhum número é calculado aqui: só formatação.
"""

from datetime import date

import pyqtgraph as pg
from PySide6.QtCore import QDate, QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QCompleter, QDateEdit, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter,
                               QTableView, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from desktop.comum import (AMARELO, AVISO, CINZA, VERDE, VERMELHO, Card, Tabela, cor_valor, em_segundo_plano, hora,
                           num, pct, reais)

pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#8b949e")


def tabela_view(modelo, ordenavel=True) -> tuple[QTableView, QSortFilterProxyModel]:
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(modelo)
    proxy.setSortRole(Qt.UserRole)
    proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
    proxy.setFilterKeyColumn(-1)
    v = QTableView()
    v.setModel(proxy)
    v.setSortingEnabled(ordenavel)
    if ordenavel:
        v.sortByColumn(0, Qt.AscendingOrder)       # sem isso o Qt começa do maior para o menor
    v.setSelectionBehavior(QAbstractItemView.SelectRows)
    v.setEditTriggers(QAbstractItemView.NoEditTriggers)
    v.setAlternatingRowColors(True)
    v.verticalHeader().setVisible(False)
    v.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    v.horizontalHeader().setStretchLastSection(True)
    return v, proxy


def aviso_label() -> QLabel:
    lbl = QLabel(AVISO, objectName="aviso")
    lbl.setWordWrap(True)
    return lbl


def fatores_texto(fatores) -> str:
    return "\n".join(f"• {f['texto']}" for f in fatores or []) or "–"


class Aba(QWidget):
    """Base: guarda o cliente e repassa o envelope (atualizado_em/provisório) para a janela."""
    envelope = Signal(dict)
    erro = Signal(str)
    abrir_ativo = Signal(str)

    def __init__(self, cliente):
        super().__init__()
        self.cliente = cliente

    def buscar(self, caminho, ao_terminar, **params):
        def pedir():
            return self.cliente.get(caminho, **params)

        def ok(resp):
            self.envelope.emit(resp)
            ao_terminar(resp["dados"])
        em_segundo_plano(pedir, ok, self.erro.emit)

    def atualizar(self):
        pass


# ---------------------------------------------------------------- Mercado

class AbaMercado(Aba):
    def __init__(self, cliente):
        super().__init__(cliente)
        lay = QVBoxLayout(self)
        cards = QHBoxLayout()
        self.c_ibov, self.c_dolar, self.c_selic, self.c_ipca = (Card(t) for t in ("Ibovespa", "Dólar (PTAX)",
                                                                                   "Selic meta", "IPCA do mês"))
        for c in (self.c_ibov, self.c_dolar, self.c_selic, self.c_ipca):
            cards.addWidget(c)
        lay.addLayout(cards)
        self.grafico = pg.PlotWidget(title="Top 5 e bottom 5 do ranking (score)")
        self.grafico.setMinimumHeight(220)
        lay.addWidget(self.grafico, 2)
        lay.addWidget(QLabel("Alertas do dia"))
        self.alertas = QListWidget()
        self.alertas.itemDoubleClicked.connect(lambda it: it.data(Qt.UserRole) and self.abrir_ativo.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.alertas, 1)
        lay.addWidget(aviso_label())

    def atualizar(self):
        self.buscar("/mercado", self._mostrar)
        em_segundo_plano(lambda: self.cliente.get("/notificacoes"), lambda r: self._alertas(r["dados"]))

    def _mostrar(self, d):
        ib = d.get("ibovespa")
        if ib:
            self.c_ibov.mostrar(num(ib["valor"], 0) if ib["nome"] == "Ibovespa" else reais(ib["valor"]),
                                f"{pct(ib['variacao_dia'])} · {ib['nome']} · {hora(ib['horario'])}"
                                + (" · provisório" if ib["provisorio"] else ""), cor_valor(ib["variacao_dia"]))
        m = d.get("macro", {})
        for card, chave, fmt in ((self.c_dolar, "ptax_venda", lambda v: reais(v)),
                                 (self.c_selic, "selic_meta", lambda v: f"{num(v)}% a.a."),
                                 (self.c_ipca, "ipca", lambda v: f"{num(v)}%")):
            if chave in m:
                card.mostrar(fmt(m[chave]["valor"]), f"referência {m[chave]['referencia']}")
        linhas = d.get("topo", []) + d.get("fundo", [])[::-1]
        self.grafico.clear()
        if linhas:
            xs = list(range(len(linhas)))
            cores = [VERDE if i < len(d.get("topo", [])) else VERMELHO for i in xs]
            self.grafico.addItem(pg.BarGraphItem(x=xs, height=[l["score"] for l in linhas], width=0.6, brushes=cores))
            self.grafico.getAxis("bottom").setTicks([[(i, l["ticker"]) for i, l in enumerate(linhas)]])
            self.grafico.setYRange(min(l["score"] for l in linhas) * 0.9, max(l["score"] for l in linhas) * 1.02)

    def _alertas(self, alertas):
        self.alertas.clear()
        cores = {"alerta": VERMELHO, "atencao": AMARELO, "info": CINZA}
        for a in alertas or [{"texto": "Nenhum alerta agora.", "nivel": "info", "ticker": None}]:
            it = QListWidgetItem(a["texto"])
            it.setForeground(pg.mkColor(cores.get(a["nivel"], CINZA)))
            it.setData(Qt.UserRole, a.get("ticker"))
            self.alertas.addItem(it)


# ---------------------------------------------------------------- Ranking

class AbaRanking(Aba):
    def __init__(self, cliente):
        super().__init__(cliente)
        lay = QVBoxLayout(self)
        topo = QHBoxLayout()
        self.filtro = QLineEdit(placeholderText="Filtrar por ticker ou nome…")
        self.info = QLabel("")
        topo.addWidget(self.filtro, 1)
        topo.addWidget(self.info)
        lay.addLayout(topo)
        self.modelo = Tabela([("#", "posicao", lambda v: str(v), False), ("Ticker", "ticker", None, False),
                              ("Nome", "nome", None, False),
                              ("Compra 0–100", "pontuacao_compra", lambda v: "–" if v is None else str(v), False),
                              ("Sinal 1m", "sinal_1m", None, False),
                              ("Score", "score", lambda v: num(v, 3), False),
                              ("Preço", "preco", reais, False), ("Dia", "variacao_dia", pct, True),
                              ("Sentimento 21d", "sentimento_21d", lambda v: num(v), True),
                              ("Volume vs média", "volume_relativo", lambda v: num(v), False),
                              ("Carteira", "na_carteira", lambda v: "✔" if v else "", False)])
        self.tabela, self.proxy = tabela_view(self.modelo)
        self.filtro.textChanged.connect(self.proxy.setFilterFixedString)
        self.tabela.doubleClicked.connect(
            lambda i: self.abrir_ativo.emit(self.modelo.linha(self.proxy.mapToSource(i).row())["ticker"]))
        lay.addWidget(self.tabela)
        lay.addWidget(QLabel("Duplo clique abre o detalhe da ação. Top 30 = indicação de compra da regra validada."))
        lay.addWidget(aviso_label())

    def atualizar(self):
        self.buscar("/ranking", self._mostrar)

    def _mostrar(self, d):
        r = d["ranking"]
        self.info.setText(f"Ranking de {r['data']}" + (" · PROVISÓRIO (intradiário)" if r["provisorio"] else " · oficial"))
        self.modelo.definir(d["linhas"])


# ---------------------------------------------------------------- Ativo

class AbaAtivo(Aba):
    def __init__(self, cliente):
        super().__init__(cliente)
        self.ticker = None
        lay = QVBoxLayout(self)
        topo = QHBoxLayout()
        self.entrada = QLineEdit(placeholderText="Ticker (ex.: PETR4) e Enter")
        self.entrada.setMaximumWidth(220)
        self.entrada.returnPressed.connect(lambda: self.abrir(self.entrada.text()))
        self.periodo = QComboBox()
        for rotulo, dias in (("1 mês", 31), ("3 meses", 92), ("1 ano", 365), ("3 anos", 1095), ("5 anos", 1825)):
            self.periodo.addItem(rotulo, dias)
        self.periodo.setCurrentIndex(2)
        self.periodo.currentIndexChanged.connect(self.atualizar)
        self.cabecalho = QLabel("Escolha uma ação.")
        self.cabecalho.setStyleSheet("font-size: 16px; font-weight: 600;")
        for w in (self.entrada, self.periodo):
            topo.addWidget(w)
        topo.addWidget(self.cabecalho, 1)
        lay.addLayout(topo)
        self.previsoes = QTextBrowser()
        self.previsoes.setMaximumHeight(190)
        lay.addWidget(self.previsoes)

        divisor = QSplitter(Qt.Horizontal)
        esquerda = QWidget()
        le = QVBoxLayout(esquerda)
        self.g_preco = pg.PlotWidget(title="Preço (ajustado por desdobramentos)", axisItems={"bottom": pg.DateAxisItem()})
        self.g_score = pg.PlotWidget(title="Posição no ranking (1 = topo)", axisItems={"bottom": pg.DateAxisItem()})
        self.g_score.invertY(True)
        le.addWidget(self.g_preco, 3)
        le.addWidget(self.g_score, 2)
        divisor.addWidget(esquerda)

        direita = QTabWidget()
        self.porque = QTextBrowser()
        self.bt_porque = QPushButton("Explicar com IA")
        self.bt_porque.clicked.connect(self._pedir_porque)
        w = QWidget()
        lw = QVBoxLayout(w)
        lw.addWidget(self.porque)
        lw.addWidget(self.bt_porque)
        direita.addTab(w, "Por quê")
        self.m_sinais = Tabela([("Sinal", "nome", None, False), ("Valor", "valor", lambda v: num(v, 3), False),
                                ("Percentil", "percentil", lambda v: "–" if v is None else f"{round(v * 100)}", False),
                                ("Nível", "nivel", None, False)])
        v_sinais, _ = tabela_view(self.m_sinais)
        direita.addTab(v_sinais, "Sinais")
        self.noticias = QTextBrowser(openExternalLinks=True)
        direita.addTab(self.noticias, "Notícias e fatos")
        divisor.addWidget(direita)
        divisor.setSizes([700, 450])
        lay.addWidget(divisor, 1)
        lay.addWidget(aviso_label())

    def definir_tickers(self, tickers):
        self.entrada.setCompleter(QCompleter(sorted(tickers)))

    def abrir(self, ticker: str):
        self.ticker = ticker.strip().upper() or None
        self.entrada.setText(self.ticker or "")
        self.porque.setPlainText("")
        self.atualizar()

    def atualizar(self):
        if self.ticker:
            self.buscar(f"/ativo/{self.ticker}", self._mostrar, dias=self.periodo.currentData())

    def _mostrar(self, d):
        c, r = d.get("cotacao") or {}, d["ranking"]
        selo = " · PROVISÓRIO" if c.get("provisorio") else ""
        pos = f"#{r['posicao']} de {r['total']} (score {num(r['score'], 3)})" if r["posicao"] else "fora do ranking"
        self.cabecalho.setText(f"{d['ticker']} · {d['nome']} · {reais(c.get('preco'))} "
                               f"<span style='color:{cor_valor(c.get('variacao_dia')) or '#e6edf3'}'>"
                               f"{pct(c.get('variacao_dia'))}</span> · {pos} · às {hora(c.get('horario'))}{selo}")
        self.previsoes.setHtml(html_previsoes(d.get("pontuacao"), d.get("previsoes"), d.get("padrao")))
        self.g_preco.clear()
        precos = [p for p in d["precos"] if p.get("fechamento")]
        if precos:
            xs = [_epoch(p["data"]) for p in precos]
            self.g_preco.plot(xs, [p["fechamento"] for p in precos], pen=pg.mkPen("#58a6ff", width=2))
        self.g_score.clear()
        if d["historico_score"]:
            h = d["historico_score"]
            self.g_score.plot([_epoch(x["data"]) for x in h], [x["posicao"] for x in h], pen=pg.mkPen(AMARELO, width=1.5))
        if not self.porque.toPlainText():
            self.porque.setPlainText("Fatores que mais pesaram:\n" + fatores_texto(d["fatores"]))
        self.m_sinais.definir(d["sinais"]["sinais"])
        html = ["<h3>Fatos relevantes</h3>"]
        for f in d["fatos_relevantes"]:
            html.append(f"<p><b>{f['data']}</b> · {f.get('evento') or ''} ({f.get('direcao') or 'sem classificação'})<br>"
                        f"{f.get('resumo') or f.get('assunto') or ''} <a href='{f.get('url')}'>documento</a></p>")
        html.append("<h3>Notícias</h3>")
        for n in d["noticias"]:
            s = n.get("sentimento")
            cor = cor_valor(s) or CINZA
            html.append(f"<p><span style='color:{cor}'>●</span> {hora(n['disponivel_em'])} · {n['fonte']} · "
                        f"<a href='{n['url']}'>{n['titulo']}</a></p>")
        self.noticias.setHtml("".join(html))

    def _pedir_porque(self):
        if not self.ticker:
            return
        self.bt_porque.setEnabled(False)
        self.porque.setPlainText("Pedindo a explicação…")

        def ok(resp):
            d = resp["dados"]
            extra = (f"\n\n⚠ Números não verificados: {', '.join(d['numeros_nao_verificados'])}"
                     if d["numeros_nao_verificados"] else "")
            self.porque.setPlainText(d["texto"] + extra + "\n\nFatores:\n" + fatores_texto(
                [{"texto": t} for t in d["dados"]["fatores"]]) + f"\n\n{d['aviso']}")
            self.bt_porque.setEnabled(True)

        def falha(msg):
            self.porque.setPlainText(f"Explicação indisponível: {msg}")
            self.bt_porque.setEnabled(True)
        em_segundo_plano(lambda: self.cliente.get(f"/ativo/{self.ticker}/porque"), ok, falha)


def html_previsoes(nota, previsoes, padrao) -> str:
    """Notas 0–100, tendência, padrão gráfico (com efeito medido) e histórico da faixa por prazo."""
    cor = {"compra": VERDE, "venda": VERMELHO}
    partes = []
    if nota:
        partes.append(f"<span style='font-size:20px'><b style='color:{VERDE}'>Nota de compra {nota['compra']}</b></span> "
                      f"<span style='color:{CINZA}'>(0 a 100)</span>")
    tend = (padrao or {}).get("tendencia")
    graf = (padrao or {}).get("grafico")
    linha = f"Tendência: <b>{tend['tendencia']}</b>" if tend else "Tendência: –"
    linha += (f" · Padrão gráfico: <b>{graf['nome']}</b> (leitura clássica: {graf['direcao_classica']})" if graf
              else " · Padrão gráfico: nenhum confirmado nos últimos 120 pregões")
    partes.append(linha)
    for e in (graf or {}).get("efeito_historico", []):
        partes.append(f"<span style='color:{CINZA}'>↳ {e['conclusao']}</span>")
    if previsoes:
        linhas = "".join(
            f"<tr><td>{p['prazo']}</td><td style='color:{cor_valor(p['retorno_medio']) or '#e6edf3'}'>{pct(p['retorno_medio'], 1)}</td>"
            f"<td>{pct(p['p25'], 0)} a {pct(p['p75'], 0)}</td><td>{pct(p['excesso_medio'], 1)}</td>"
            f"<td>{pct(p['chance_superar'], 0, False)}</td><td style='color:{cor.get(p['sinal'], CINZA)}'>{p['sinal']}</td>"
            f"<td style='color:{CINZA}'>{p['comportamento']}</td></tr>" for p in previsoes)
        partes.append("<table cellpadding='3'><tr style='color:#8b949e'><td>Prazo</td><td>Ganho esperado*</td><td>Faixa provável</td>"
                      "<td>Contra o mercado</td><td>Chance de superar</td><td>Sinal</td><td>Comportamento</td></tr>"
                      + linhas + "</table>")
        p0 = previsoes[0]
        partes.append(f"<span style='color:{CINZA}; font-size:11px'>* Não é promessa: histórico fora da amostra de ações na "
                      f"mesma faixa ({p0['faixa_min']}–{p0['faixa_max']}), {p0['periodo_inicio']} a {p0['periodo_fim']}.</span>")
    return "<br>".join(partes)


def _epoch(data_iso: str) -> float:
    """'AAAA-MM-DD' -> segundos (meio-dia UTC) para o eixo de datas do pyqtgraph."""
    return (date.fromisoformat(data_iso[:10]) - date(1970, 1, 1)).total_seconds() + 12 * 3600


# ---------------------------------------------------------------- Carteira

class DialogoOperacao(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nova operação")
        form = QFormLayout(self)
        self.ticker = QLineEdit(placeholderText="PETR4")
        self.tipo = QComboBox()
        self.tipo.addItems(["compra", "venda"])
        self.data = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.data.setMaximumDate(QDate.currentDate())
        self.qtd = QDoubleSpinBox(decimals=0, maximum=1e9)
        self.preco = QDoubleSpinBox(decimals=2, maximum=1e7, prefix="R$ ")
        self.custos = QDoubleSpinBox(decimals=2, maximum=1e6, prefix="R$ ")
        for rotulo, w in (("Ticker", self.ticker), ("Tipo", self.tipo), ("Data", self.data), ("Quantidade", self.qtd),
                          ("Preço", self.preco), ("Custos (corretagem/taxas)", self.custos)):
            form.addRow(rotulo, w)
        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        form.addRow(botoes)

    def operacao(self) -> dict:
        return {"ticker": self.ticker.text().strip().upper(), "tipo": self.tipo.currentText(),
                "data": self.data.date().toString("yyyy-MM-dd"), "quantidade": self.qtd.value(),
                "preco": self.preco.value(), "custos": self.custos.value()}


class AbaCarteira(Aba):
    def __init__(self, cliente):
        super().__init__(cliente)
        lay = QVBoxLayout(self)
        cards = QHBoxLayout()
        self.c_valor, self.c_ganho, self.c_dia, self.c_ibov = (Card(t) for t in (
            "Valor da carteira", "Ganho desde a compra", "Ganho no dia", "Ibovespa no mesmo período"))
        for c in (self.c_valor, self.c_ganho, self.c_dia, self.c_ibov):
            cards.addWidget(c)
        lay.addLayout(cards)
        botoes = QHBoxLayout()
        for texto, acao in (("Nova operação", self._nova), ("Importar extrato…", self._importar),
                            ("Sincronizar XP", self._sincronizar)):
            b = QPushButton(texto)
            b.clicked.connect(acao)
            botoes.addWidget(b)
        botoes.addStretch(1)
        self.info = QLabel("")
        botoes.addWidget(self.info)
        lay.addLayout(botoes)

        divisor = QSplitter(Qt.Vertical)
        self.m_pos = Tabela([("Ticker", "ticker", None, False), ("Qtd", "quantidade", lambda v: num(v, 0), False),
                             ("Preço médio", "preco_medio", reais, False), ("Preço", "preco", reais, False),
                             ("Valor", "valor", reais, False), ("Peso", "peso", lambda v: pct(v, 1, False), False),
                             ("Dia", "variacao_dia", pct, True), ("Ganho", "ganho", reais, True),
                             ("Ganho %", "ganho_pct", pct, True), ("Mês (papel)", "retorno_mes", pct, True),
                             ("Ano (papel)", "retorno_ano", pct, True), ("Proventos", "proventos", reais, False),
                             ("Ranking", "posicao_ranking", lambda v: "–" if v is None else f"#{v}", False),
                             ("Compra", "pontuacao_compra", lambda v: "–" if v is None else str(v), False),
                             ("Lucro se vender", "lucro_venda", reais, True),
                             ("IR se tributado", "ir_venda", reais, False),
                             ("Leitura", "leitura", None, False)])
        v_pos, self.p_pos = tabela_view(self.m_pos)
        v_pos.doubleClicked.connect(lambda i: self.abrir_ativo.emit(self.m_pos.linha(self.p_pos.mapToSource(i).row())["ticker"]))
        divisor.addWidget(v_pos)

        baixo = QSplitter(Qt.Horizontal)
        self.indicacoes = QTextBrowser()
        baixo.addWidget(self.indicacoes)
        self.g_evol = pg.PlotWidget(title="Patrimônio × investido (R$)", axisItems={"bottom": pg.DateAxisItem()})
        self.g_evol.addLegend()
        baixo.addWidget(self.g_evol)
        baixo.setSizes([500, 600])
        divisor.addWidget(baixo)
        lay.addWidget(divisor, 1)
        lay.addWidget(aviso_label())

    def atualizar(self):
        self.buscar("/carteira", self._mostrar)
        em_segundo_plano(lambda: self.cliente.get("/carteira/indicacoes"), lambda r: self._indicacoes(r["dados"]))
        em_segundo_plano(lambda: self.cliente.get("/carteira/evolucao"), lambda r: self._evolucao(r["dados"]))

    def _mostrar(self, d):
        t = d["totais"]
        self.c_valor.mostrar(reais(t["valor"]), f"custo {reais(t['custo'])}")
        self.c_ganho.mostrar(reais(t["ganho"]), pct(t["ganho_pct"]), cor_valor(t["ganho"]))
        self.c_dia.mostrar(reais(t["ganho_dia"]), "", cor_valor(t["ganho_dia"]))
        self.c_ibov.mostrar(pct(t["ibovespa_desde_inicio"]), f"desde {t['inicio'] or '–'} (BOVA11)",
                            cor_valor(t["ibovespa_desde_inicio"]))
        fonte = f"XP sincronizada {hora(d['sincronizada_em'])}" if d["sincronizada_em"] else "operações registradas"
        if not d["posicoes"]:
            fonte = "carteira vazia: registre uma operação, importe o extrato da B3/XP ou sincronize a XP (Meu Pluggy)"
        self.info.setText(f"Fonte: {fonte}" + (f" · ⚠ {len(d['avisos'])} aviso(s)" if d["avisos"] else ""))
        self.info.setToolTip("\n".join(d["avisos"]))
        self.m_pos.definir([{**p, "lucro_venda": (p.get("vender_agora") or {}).get("lucro"),
                             "ir_venda": (p.get("vender_agora") or {}).get("ir_se_tributado")} for p in d["posicoes"]])

    def _indicacoes(self, d):
        r = d.get("ranking") or {}
        partes = [f"<p style='color:{CINZA}'>Ranking de {r.get('data')}{' (provisório)' if r.get('provisorio') else ''}. "
                  f"{d['regra']}</p>"]
        def bloco(titulo, cor, itens, campo_pos):
            partes.append(f"<h3 style='color:{cor}'>{titulo} ({len(itens)})</h3>")
            for i in itens:
                fat = "; ".join(f["texto"] for f in i.get("fatores", [])[:3])
                partes.append(f"<p><b>{i['ticker']}</b> #{i.get(campo_pos) or '–'} — <span style='color:{CINZA}'>{fat}</span></p>")
        bloco("Considerar vender", VERMELHO, d["vender"], "posicao_ranking")
        bloco("Observar", AMARELO, d["observar"], "posicao_ranking")
        bloco("Comprar (top 30 fora da carteira)", VERDE, d["comprar"], "posicao")
        if d["sem_leitura"]:
            partes.append(f"<p style='color:{CINZA}'>Sem leitura do modelo: {', '.join(p['ticker'] for p in d['sem_leitura'])}</p>")
        partes.append(f"<p style='color:{CINZA}'><i>{d['aviso']}</i></p>")
        self.indicacoes.setHtml("".join(partes))

    def _evolucao(self, serie):
        self.g_evol.clear()
        if not serie:
            return
        xs = [_epoch(p["data"]) for p in serie]
        self.g_evol.plot(xs, [p["valor"] for p in serie], pen=pg.mkPen("#58a6ff", width=2), name="Patrimônio")
        self.g_evol.plot(xs, [p["investido"] for p in serie], pen=pg.mkPen(CINZA, width=1, style=Qt.DashLine),
                         name="Investido")

    def _nova(self):
        dlg = DialogoOperacao(self)
        if dlg.exec() != QDialog.Accepted:
            return
        em_segundo_plano(lambda: self.cliente.post("/carteira/operacao", json=dlg.operacao()),
                         lambda _: self.atualizar(), lambda m: QMessageBox.warning(self, "Operação", m))

    def _importar(self):
        caminho, _ = QFileDialog.getOpenFileName(self, "Extrato de negociação", "",
                                                 "Planilhas (*.csv *.xlsx *.xls);;Todos (*)")
        if not caminho:
            return

        def enviar():
            with open(caminho, "rb") as f:
                return self.cliente.post("/carteira/importar", files={"arquivo": (caminho.split("/")[-1], f.read())})

        def ok(r):
            ruins = "\n".join(f"linha {x['linha']}: {x['motivo']}" for x in r["nao_reconhecidas"][:15])
            QMessageBox.information(self, "Importação", f"{r['importadas']} operações novas, {r['ja_existiam']} já existiam."
                                    + (f"\n\nNão reconhecidas ({len(r['nao_reconhecidas'])}):\n{ruins}" if ruins else ""))
            self.atualizar()
        em_segundo_plano(enviar, ok, lambda m: QMessageBox.warning(self, "Importação", m))

    def _sincronizar(self):
        em_segundo_plano(lambda: self.cliente.post("/carteira/sincronizar"),
                         lambda r: (QMessageBox.information(self, "XP", f"{r['posicoes']} posições sincronizadas."),
                                    self.atualizar()),
                         lambda m: QMessageBox.warning(self, "XP", m))


# ---------------------------------------------------------------- Relatório

class AbaRelatorio(Aba):
    def __init__(self, cliente):
        super().__init__(cliente)
        self.data = "ultimo"
        self.vizinhos = (None, None)
        lay = QVBoxLayout(self)
        nav = QHBoxLayout()
        self.bt_ant, self.bt_prox = QPushButton("◀ Anterior"), QPushButton("Próximo ▶")
        self.bt_ant.clicked.connect(lambda: self._ir(self.vizinhos[0]))
        self.bt_prox.clicked.connect(lambda: self._ir(self.vizinhos[1]))
        self.titulo = QLabel("")
        nav.addWidget(self.bt_ant)
        nav.addWidget(self.titulo, 1, Qt.AlignCenter)
        nav.addWidget(self.bt_prox)
        lay.addLayout(nav)
        self.texto = QTextBrowser(openExternalLinks=True)
        lay.addWidget(self.texto)

    def _ir(self, data):
        if data:
            self.data = data
            self.atualizar()

    def atualizar(self):
        self.buscar(f"/relatorio/{self.data}", self._mostrar)

    def _mostrar(self, d):
        self.vizinhos = (d["anterior"], d["proximo"])
        self.bt_ant.setEnabled(bool(d["anterior"]))
        self.bt_prox.setEnabled(bool(d["proximo"]))
        self.titulo.setText(f"Relatório de {d['data']}")
        if self.data != "ultimo" and not d["proximo"]:
            self.data = "ultimo"             # na ponta, volta a acompanhar o mais recente
        rolagem = self.texto.verticalScrollBar().value()
        self.texto.setMarkdown(d["markdown"])
        self.texto.verticalScrollBar().setValue(rolagem)


# ---------------------------------------------------------------- Chat

class AbaChat(Aba):
    def __init__(self, cliente):
        super().__init__(cliente)
        self.mensagens: list[dict] = []          # histórico só da sessão (não persiste)
        lay = QVBoxLayout(self)
        self.historico = QTextBrowser()
        lay.addWidget(self.historico, 1)
        self.sugestoes = QHBoxLayout()
        lay.addLayout(self.sugestoes)
        linha = QHBoxLayout()
        self.entrada = QLineEdit(placeholderText="Pergunte sobre ações, o ranking ou sua carteira…")
        self.entrada.returnPressed.connect(self._enviar)
        self.bt = QPushButton("Enviar")
        self.bt.clicked.connect(self._enviar)
        linha.addWidget(self.entrada, 1)
        linha.addWidget(self.bt)
        lay.addLayout(linha)
        lay.addWidget(aviso_label())
        self._carregou_sugestoes = False

    def atualizar(self):
        if not self._carregou_sugestoes:
            em_segundo_plano(lambda: self.cliente.get("/chat/sugestoes"), lambda r: self._mostrar_sugestoes(r["dados"]))

    def _mostrar_sugestoes(self, sugestoes):
        self._carregou_sugestoes = True
        for s in sugestoes[:4]:
            b = QPushButton(s)
            b.clicked.connect(lambda _=False, s=s: (self.entrada.setText(s), self._enviar()))
            self.sugestoes.addWidget(b)

    def _render(self, extra: str = ""):
        partes = []
        for m in self.mensagens:
            quem = "Você" if m["papel"] == "usuario" else "Assistente"
            cor = "#58a6ff" if m["papel"] == "usuario" else VERDE
            partes.append(f"<p><b style='color:{cor}'>{quem}:</b></p>{m.get('html') or m['texto']}")
        self.historico.setHtml("".join(partes) + extra)
        self.historico.verticalScrollBar().setValue(self.historico.verticalScrollBar().maximum())

    def _enviar(self):
        texto = self.entrada.text().strip()
        if not texto or not self.bt.isEnabled():
            return
        self.entrada.clear()
        self.mensagens.append({"papel": "usuario", "texto": texto})
        self.bt.setEnabled(False)
        self._render(f"<p style='color:{CINZA}'>pensando…</p>")
        pedido = [{"papel": m["papel"], "texto": m["texto"]} for m in self.mensagens]

        def ok(resp):
            d = resp["dados"]
            doc = QTextBrowser()
            doc.setMarkdown(d["resposta"])
            html = doc.toHtml()
            if d["numeros_nao_verificados"]:
                html += f"<p style='color:{AMARELO}'>⚠ números não verificados: {', '.join(d['numeros_nao_verificados'])}</p>"
            self.mensagens.append({"papel": "assistente", "texto": d["resposta"], "html": html})
            self.bt.setEnabled(True)
            self._render()

        def falha(msg):
            self.mensagens.pop()
            self.bt.setEnabled(True)
            self._render(f"<p style='color:{VERMELHO}'>Não deu para responder agora: {msg}</p>")
        em_segundo_plano(lambda: self.cliente.post("/chat", json={"mensagens": pedido}), ok, falha)
