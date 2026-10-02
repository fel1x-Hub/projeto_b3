import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "../api.js";
import { Aviso, Card, Carregando, Erro } from "../comum.jsx";
import { corValor, hora, num, pct, reais } from "../fmt.js";

const COR_ALERTA = { alerta: "text-baixa", atencao: "text-atencao", info: "text-apagado" };

export default function Mercado({ aoEnvelope, abrirAtivo, logado }) {
  const { dados, erro } = useApi("/mercado", { aoEnvelope });
  const alertas = useApi(logado ? "/notificacoes" : null);   // alertas envolvem a carteira
  if (!dados) return erro ? <Erro erro={erro} /> : <Carregando />;
  const ib = dados.ibovespa;
  const m = dados.macro || {};
  const barras = [...dados.topo, ...[...dados.fundo].reverse()].map((l, i) => ({ ...l, topo: i < dados.topo.length }));
  return (
    <div>
      <Erro erro={erro} />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Card titulo="Ibovespa" cor={corValor(ib?.variacao_dia)}
              valor={ib ? (ib.nome === "Ibovespa" ? num(ib.valor, 0) : reais(ib.valor)) : "–"}
              detalhe={ib ? `${pct(ib.variacao_dia)} · ${ib.nome} · ${hora(ib.horario)}${ib.provisorio ? " · provisório" : ""}` : ""} />
        <Card titulo="Dólar (PTAX)" valor={reais(m.ptax_venda?.valor)} detalhe={`referência ${m.ptax_venda?.referencia ?? "–"}`} />
        <Card titulo="Selic meta" valor={m.selic_meta ? `${num(m.selic_meta.valor)}% a.a.` : "–"}
              detalhe={`referência ${m.selic_meta?.referencia ?? "–"}`} />
        <Card titulo="IPCA do mês" valor={m.ipca ? `${num(m.ipca.valor)}%` : "–"} detalhe={`referência ${m.ipca?.referencia ?? "–"}`} />
      </div>
      <h2 className="mt-5 mb-2 text-apagado text-sm">Top 5 e bottom 5 do ranking (score)</h2>
      <div className="h-64 bg-painel border border-borda rounded-lg p-2">
        <ResponsiveContainer>
          <BarChart data={barras}>
            <XAxis dataKey="ticker" stroke="#8b949e" fontSize={12} />
            <YAxis stroke="#8b949e" fontSize={12} domain={["auto", "auto"]} tickFormatter={(v) => num(v, 2)} />
            <Tooltip formatter={(v) => num(v, 3)} contentStyle={{ background: "#161b22", border: "1px solid #30363d" }} />
            <Bar dataKey="score" onClick={(d) => abrirAtivo(d.ticker)} cursor="pointer">
              {barras.map((b) => <Cell key={b.ticker} fill={b.topo ? "#3fb950" : "#f85149"} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {logado && <>
      <h2 className="mt-5 mb-2 text-apagado text-sm">Alertas do dia</h2>
      <ul className="bg-painel border border-borda rounded-lg p-3 space-y-1 text-sm">
        {(alertas.dados || []).length === 0 && <li className="text-apagado">Nenhum alerta agora.</li>}
        {(alertas.dados || []).map((a, i) => (
          <li key={i} className={`${COR_ALERTA[a.nivel] || ""} ${a.ticker ? "cursor-pointer hover:underline" : ""}`}
              onClick={() => a.ticker && abrirAtivo(a.ticker)}>{a.texto}</li>
        ))}
      </ul>
      </>}
      <Aviso />
    </div>
  );
}
