import { useState } from "react";
import { useApi } from "../api.js";
import { Aviso, Carregando, Erro, Tabela } from "../comum.jsx";
import { num, pct, reais } from "../fmt.js";

export const COLUNAS_RANKING = [
  { titulo: "#", chave: "posicao", fmt: (v) => String(v) },
  { titulo: "Ticker", chave: "ticker" },
  { titulo: "Nome", chave: "nome" },
  { titulo: "Compra (0–100)", chave: "pontuacao_compra", fmt: (v) => (v ?? "–").toString() },
  { titulo: "Venda (0–100)", chave: "pontuacao_venda", fmt: (v) => (v ?? "–").toString() },
  { titulo: "Sinal 1m", chave: "sinal_1m", colorir: false },
  { titulo: "Score", chave: "score", fmt: (v) => num(v, 3) },
  { titulo: "Preço", chave: "preco", fmt: reais },
  { titulo: "Dia", chave: "variacao_dia", fmt: (v) => pct(v), colorir: true },
  { titulo: "Sentimento 21d", chave: "sentimento_21d", fmt: (v) => num(v), colorir: true },
  { titulo: "Volume vs média", chave: "volume_relativo", fmt: (v) => num(v) },
  { titulo: "Carteira", chave: "na_carteira", fmt: (v) => (v ? "✔" : "") },
];

export function TabelaRanking({ linhas, filtro = "", abrirAtivo }) {
  const f = filtro.trim().toLowerCase();
  const visiveis = f ? linhas.filter((l) => `${l.ticker} ${l.nome}`.toLowerCase().includes(f)) : linhas;
  return <Tabela colunas={COLUNAS_RANKING} linhas={visiveis} aoClicar={(l) => abrirAtivo(l.ticker)} />;
}

export default function Ranking({ aoEnvelope, abrirAtivo }) {
  const { dados, erro } = useApi("/ranking", { aoEnvelope });
  const [filtro, setFiltro] = useState("");
  if (!dados) return erro ? <Erro erro={erro} /> : <Carregando />;
  const r = dados.ranking;
  return (
    <div>
      <Erro erro={erro} />
      <div className="flex flex-wrap gap-3 items-center mb-3">
        <input value={filtro} onChange={(e) => setFiltro(e.target.value)} placeholder="Filtrar por ticker ou nome…"
               className="bg-painel border border-borda rounded px-3 py-1.5 flex-1 min-w-48" />
        <span className="text-sm">
          Ranking de {r.data} · {r.provisorio ? <b className="text-atencao">PROVISÓRIO (intradiário)</b> : "oficial"}
        </span>
      </div>
      <div className="max-h-[70vh] overflow-auto">
        <TabelaRanking linhas={dados.linhas} filtro={filtro} abrirAtivo={abrirAtivo} />
      </div>
      <p className="text-sm text-apagado mt-2">Clique numa linha para o detalhe. Top 30 = indicação de compra da regra validada.</p>
      <Aviso />
    </div>
  );
}
