"""Peças comuns do app: tema escuro, chamadas em segundo plano, formatação e tabela."""

from datetime import datetime
from zoneinfo import ZoneInfo

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout

FUSO = ZoneInfo("America/Sao_Paulo")
VERDE, VERMELHO, AMARELO, CINZA = "#3fb950", "#f85149", "#d29922", "#8b949e"
AVISO = "Não é recomendação de investimento. Material de apoio; a decisão e a execução são suas."


# ---------------------------------------------------------------- tema

def aplicar_tema(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    cores = {QPalette.Window: "#0d1117", QPalette.WindowText: "#e6edf3", QPalette.Base: "#161b22",
             QPalette.AlternateBase: "#1c2128", QPalette.Text: "#e6edf3", QPalette.Button: "#21262d",
             QPalette.ButtonText: "#e6edf3", QPalette.Highlight: "#1f6feb", QPalette.HighlightedText: "#ffffff",
             QPalette.ToolTipBase: "#161b22", QPalette.ToolTipText: "#e6edf3", QPalette.PlaceholderText: CINZA}
    for papel, cor in cores.items():
        p.setColor(papel, QColor(cor))
    app.setPalette(p)
    app.setStyleSheet("""
        QFrame#card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; }
        QLabel#titulo_card { color: #8b949e; font-size: 11px; }
        QLabel#valor_card { font-size: 20px; font-weight: 600; }
        QLabel#aviso { color: #8b949e; font-size: 11px; }
        QLabel#selo { background: #d29922; color: #0d1117; border-radius: 4px; padding: 1px 6px; font-weight: 600; }
        QTableView { gridline-color: #30363d; }
        QHeaderView::section { background: #21262d; color: #e6edf3; border: 0; padding: 4px; }
        QPushButton { padding: 5px 12px; }
        QTabBar::tab { padding: 7px 16px; }
    """)


# ---------------------------------------------------------------- tarefas

class _Sinais(QObject):
    ok = Signal(object)
    erro = Signal(str)


class _Tarefa(QRunnable):
    def __init__(self, funcao):
        super().__init__()
        self.funcao, self.sinais = funcao, _Sinais()

    def run(self):
        try:
            resultado = self.funcao()
        except Exception as e:  # noqa: BLE001 - qualquer falha vira mensagem na tela
            self.sinais.erro.emit(str(e) or e.__class__.__name__)
        else:
            self.sinais.ok.emit(resultado)


_pendentes: set = set()


def em_segundo_plano(funcao, ao_terminar, ao_falhar=None) -> None:
    """Roda `funcao` fora da thread da interface (a tela nunca trava esperando a API)."""
    tarefa = _Tarefa(funcao)
    _pendentes.add(tarefa.sinais)                  # mantém os sinais vivos até a resposta
    tarefa.sinais.ok.connect(ao_terminar)
    if ao_falhar:
        tarefa.sinais.erro.connect(ao_falhar)
    tarefa.sinais.ok.connect(lambda _: _pendentes.discard(tarefa.sinais))
    tarefa.sinais.erro.connect(lambda _: _pendentes.discard(tarefa.sinais))
    QThreadPool.globalInstance().start(tarefa)


# ---------------------------------------------------------------- formatação

def pct(x, casas: int = 2, sinal: bool = True) -> str:
    if x is None:
        return "–"
    return (f"{x * 100:+.{casas}f}%" if sinal else f"{x * 100:.{casas}f}%").replace(".", ",")


def num(x, casas: int = 2) -> str:
    if x is None:
        return "–"
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def reais(x) -> str:
    return "–" if x is None else f"R$ {num(x)}"


def hora(iso: str | None) -> str:
    """Timestamp UTC -> 'HH:MM' de Brasília (ou 'dd/mm HH:MM' se não for hoje)."""
    if not iso:
        return "–"
    dt = datetime.fromisoformat(iso).astimezone(FUSO)
    hoje = datetime.now(FUSO).date()
    return dt.strftime("%H:%M") if dt.date() == hoje else dt.strftime("%d/%m %H:%M")


def cor_valor(x) -> str | None:
    if x is None:
        return None
    return VERDE if x > 0 else VERMELHO if x < 0 else None


# ---------------------------------------------------------------- widgets

class Card(QFrame):
    def __init__(self, titulo: str):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        self.titulo = QLabel(titulo, objectName="titulo_card")
        self.valor = QLabel("–", objectName="valor_card")
        self.detalhe = QLabel("", objectName="titulo_card")
        for w in (self.titulo, self.valor, self.detalhe):
            lay.addWidget(w)

    def mostrar(self, valor: str, detalhe: str = "", cor: str | None = None):
        self.valor.setText(valor)
        self.valor.setStyleSheet(f"color: {cor};" if cor else "")
        self.detalhe.setText(detalhe)


class Tabela(QAbstractTableModel):
    """colunas: [(título, chave, formatador, colorir?)]; linhas: lista de dicts da API."""

    def __init__(self, colunas):
        super().__init__()
        self.colunas, self.linhas = colunas, []

    def definir(self, linhas):
        self.beginResetModel()
        self.linhas = linhas or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.linhas)

    def columnCount(self, parent=QModelIndex()):
        return len(self.colunas)

    def headerData(self, secao, orientacao, papel=Qt.DisplayRole):
        if papel == Qt.DisplayRole and orientacao == Qt.Horizontal:
            return self.colunas[secao][0]
        return None

    def data(self, indice, papel=Qt.DisplayRole):
        titulo, chave, fmt, colorir = self.colunas[indice.column()]
        valor = self.linhas[indice.row()].get(chave)
        if papel == Qt.DisplayRole:
            return fmt(valor) if fmt else ("–" if valor is None else str(valor))
        if papel == Qt.ForegroundRole and colorir and cor_valor(valor):
            return QBrush(QColor(cor_valor(valor)))
        if papel == Qt.TextAlignmentRole and fmt is not None:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if papel == Qt.UserRole:               # ordenação numérica
            return valor
        return None

    def linha(self, i: int) -> dict:
        return self.linhas[i]
