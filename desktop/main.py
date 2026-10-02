"""App desktop (Qt / PySide6) do Projeto B3.

Rodar:  python desktop/main.py      (ou pythonw, sem janela de console)

Consome só a API (regra 10). Sem API no ar em API_URL, sobe uma embutida.
Atualiza sozinho (regra 15): a aba visível a cada 60 s com o pregão aberto e a
cada 5 min com ele fechado; a barra de status mostra quando o dado ficou pronto
e se é provisório.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QTabWidget  # noqa: E402

from desktop import telas  # noqa: E402
from desktop.cliente import ClienteAPI, garantir_api  # noqa: E402
from desktop.comum import AMARELO, VERDE, aplicar_tema, em_segundo_plano, hora  # noqa: E402

INTERVALO_ABERTO_MS = 60_000
INTERVALO_FECHADO_MS = 300_000


class Janela(QMainWindow):
    def __init__(self, cliente: ClienteAPI):
        super().__init__()
        self.cliente = cliente
        self.setWindowTitle("Projeto B3 · apoio à decisão")
        self.resize(1280, 820)
        self.abas = QTabWidget()
        self.setCentralWidget(self.abas)
        self.mercado = telas.AbaMercado(cliente)
        self.ranking = telas.AbaRanking(cliente)
        self.ativo = telas.AbaAtivo(cliente)
        self.carteira = telas.AbaCarteira(cliente)
        self.relatorio = telas.AbaRelatorio(cliente)
        self.chat = telas.AbaChat(cliente)
        for aba, nome in ((self.mercado, "Mercado"), (self.ranking, "Ranking"), (self.ativo, "Ação"),
                          (self.carteira, "Carteira"), (self.relatorio, "Relatório"), (self.chat, "Chat IA")):
            self.abas.addTab(aba, nome)
            aba.envelope.connect(self._status)
            aba.erro.connect(self._erro)
            aba.abrir_ativo.connect(self.abrir_ativo)
        self.abas.currentChanged.connect(lambda _: self.atualizar())

        self.l_mercado, self.l_atualizado, self.l_selo = QLabel(), QLabel(), QLabel(objectName="selo")
        for w in (self.l_mercado, self.l_atualizado, self.l_selo):
            self.statusBar().addPermanentWidget(w)
        self.l_selo.hide()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.atualizar)
        self.timer.start(INTERVALO_ABERTO_MS)
        em_segundo_plano(lambda: cliente.get("/ranking"),
                         lambda r: self.ativo.definir_tickers([l["ticker"] for l in r["dados"]["linhas"]]))
        self.atualizar()

    def atualizar(self):
        self.abas.currentWidget().atualizar()

    def abrir_ativo(self, ticker: str):
        self.abas.setCurrentWidget(self.ativo)
        self.ativo.abrir(ticker)

    def _status(self, env: dict):
        aberto = env.get("mercado_aberto")
        self.l_mercado.setText("● Pregão aberto" if aberto else "○ Mercado fechado")
        self.l_mercado.setStyleSheet(f"color: {VERDE if aberto else '#8b949e'};")
        if env.get("atualizado_em"):
            self.l_atualizado.setText(f"  dados de {hora(env['atualizado_em'])}  ")
        self.l_selo.setText("PROVISÓRIO")
        self.l_selo.setVisible(bool(env.get("provisorio")))
        self.l_selo.setToolTip("Valor intradiário (cotação com ~15 min de atraso / ranking provisório); "
                               "o oficial sai depois do fechamento.")
        intervalo = INTERVALO_ABERTO_MS if aberto else INTERVALO_FECHADO_MS
        if self.timer.interval() != intervalo:
            self.timer.setInterval(intervalo)
        self.statusBar().clearMessage()
        self.statusBar().setStyleSheet("")

    def _erro(self, msg: str):
        # mantém o último dado válido na tela e avisa (regra 15)
        self.statusBar().showMessage(f"⚠ Falha ao atualizar: {msg} — mostrando o último dado válido")
        self.statusBar().setStyleSheet(f"color: {AMARELO};")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Projeto B3")
    aplicar_tema(app)
    cliente = ClienteAPI()
    if not garantir_api(cliente):
        QMessageBox.critical(None, "Projeto B3", f"A API não respondeu em {cliente.url}.\n"
                             "Confira o API_TOKEN no .env e o log em logs/app.log.")
        return 1
    janela = Janela(cliente)
    janela.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
