"""App desktop (Qt / PySide6) do Projeto B3.

Rodar:  python desktop/main.py      (ou pythonw, sem janela de console)

Consome só a API (regra 10): a da nuvem configurada em "Conexão…" (guardada nas
configurações do usuário), senão uma local; rodando do código-fonte, sobe uma embutida.
Atualiza sozinho (regra 15): a aba visível a cada 60 s com o pregão aberto e a
cada 5 min com ele fechado; a barra de status mostra quando o dado ficou pronto
e se é provisório.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os  # noqa: E402
import time  # noqa: E402

from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,  # noqa: E402
                               QMainWindow, QMessageBox, QProgressDialog, QTabWidget)

from desktop import telas  # noqa: E402
from desktop.cliente import ClienteAPI, conectar, entrar  # noqa: E402
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

        self.menuBar().addAction("Conexão…", self._conexao)

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

    def _conexao(self):
        if DialogoConexao(self).exec() == QDialog.Accepted:
            QMessageBox.information(self, "Conexão", "Feche e abra o app para usar a nova conexão.")

    def _erro(self, msg: str):
        # mantém o último dado válido na tela e avisa (regra 15)
        self.statusBar().showMessage(f"⚠ Falha ao atualizar: {msg} — mostrando o último dado válido")
        self.statusBar().setStyleSheet(f"color: {AMARELO};")


def configuracao() -> tuple[str, str]:
    """(url, token): configurações do usuário; na falta, o .env (API_URL / API_TOKEN)."""
    s = QSettings("ProjetoB3", "app")
    return (s.value("api/url", "") or os.getenv("API_URL", ""), s.value("api/token", "") or os.getenv("API_TOKEN", ""))


class DialogoConexao(QDialog):
    """Endereço da API e login. Guarda só o endereço e a sessão (nunca a senha) nas configurações do usuário."""

    def __init__(self, parent=None, mensagem: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Conexão com a API")
        form = QFormLayout(self)
        if mensagem:
            aviso = QLabel(mensagem)
            aviso.setWordWrap(True)
            form.addRow(aviso)
        url, _ = configuracao()
        self.url = QLineEdit(url or "https://projeto-b3-api.onrender.com")
        self.usuario = QLineEdit(placeholderText="Usuário")
        self.senha = QLineEdit(echoMode=QLineEdit.Password, placeholderText="Senha")
        self.erro = QLabel("")
        self.erro.setStyleSheet("color: #f85149;")
        form.addRow("Endereço da API", self.url)
        form.addRow("Usuário", self.usuario)
        form.addRow("Senha", self.senha)
        form.addRow(self.erro)
        botoes = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self._salvar)
        botoes.rejected.connect(self.reject)
        form.addRow(botoes)

    def _salvar(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        url = self.url.text().strip()
        self.erro.setText("Entrando… (o servidor grátis pode levar ~1 min para acordar)")
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            sessao = entrar(url, self.usuario.text(), self.senha.text())
        except Exception as e:  # noqa: BLE001 - mostra o motivo no próprio diálogo
            self.erro.setText(f"Não deu para entrar: {e}")
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        s = QSettings("ProjetoB3", "app")
        s.setValue("api/url", url)
        s.setValue("api/token", sessao)
        self.accept()


def abrir_conexao(app) -> ClienteAPI | None:
    """Conecta sem travar a tela (a API da nuvem pode levar ~1 min para acordar)."""
    while True:
        url, token = configuracao()
        espera = QProgressDialog("Conectando à API…", "Cancelar", 0, 0)
        espera.setWindowTitle("Projeto B3")
        espera.setMinimumWidth(460)
        espera.show()
        resultado = {}
        em_segundo_plano(lambda: conectar(url, token), lambda c: resultado.update(c=c),
                         lambda m: resultado.update(c=None, erro=m))
        while "c" not in resultado and not espera.wasCanceled():
            app.processEvents()
            time.sleep(0.05)
        cancelado = espera.wasCanceled()   # antes do close(): fechar o diálogo também emite canceled()
        espera.close()
        if cancelado:
            return None
        cliente = resultado["c"]
        if cliente and cliente.token_valido():
            return cliente
        motivo = ("Entre com seu usuário e senha." if cliente else
                  "Nenhuma API respondeu (nem a configurada, nem uma local em 127.0.0.1:8000).")
        if DialogoConexao(None, motivo).exec() != QDialog.Accepted:
            return None


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Projeto B3")
    aplicar_tema(app)
    cliente = abrir_conexao(app)
    if cliente is None:
        return 1
    janela = Janela(cliente)
    janela.setWindowTitle(f"Projeto B3 · apoio à decisão · {cliente.url}")
    janela.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
