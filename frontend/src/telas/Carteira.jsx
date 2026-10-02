import { useState } from "react";
import { Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { chamar, useApi } from "../api.js";
import { Aviso, Card, Carregando, Erro, Tabela } from "../comum.jsx";
import { corValor, hora, num, pct, reais } from "../fmt.js";

export const COLUNAS_CARTEIRA = [
  { titulo: "Ticker", chave: "ticker" },
  { titulo: "Qtd", chave: "quantidade", fmt: (v) => num(v, 0) },
  { titulo: "Preço médio", chave: "preco_medio", fmt: reais },
  { titulo: "Preço", chave: "preco", fmt: reais },
  { titulo: "Valor", chave: "valor", fmt: reais },
  { titulo: "Peso", chave: "peso", fmt: (v) => pct(v, 1, false) },
  { titulo: "Dia", chave: "variacao_dia", fmt: (v) => pct(v), colorir: true },
  { titulo: "Ganho", chave: "ganho", fmt: reais, colorir: true },
  { titulo: "Ganho %", chave: "ganho_pct", fmt: (v) => pct(v), colorir: true },
  { titulo: "Mês (papel)", chave: "retorno_mes", fmt: (v) => pct(v), colorir: true },
  { titulo: "Ano (papel)", chave: "retorno_ano", fmt: (v) => pct(v), colorir: true },
  { titulo: "Proventos", chave: "proventos", fmt: reais },
  { titulo: "Ranking", chave: "posicao_ranking", fmt: (v) => (v ? `#${v}` : "–") },
  { titulo: "Compra", chave: "pontuacao_compra", fmt: (v) => (v ?? "–").toString() },
  { titulo: "Lucro se vender", chave: "lucro_venda", fmt: reais, colorir: true },
  { titulo: "IR se tributado", chave: "ir_venda", fmt: reais },
  { titulo: "Leitura", chave: "leitura" },
];

export function ResumoCarteira({ dados }) {
  const t = dados.totais;
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <Card titulo="Valor da carteira" valor={reais(t.valor)} detalhe={`custo ${reais(t.custo)}`} />
      <Card titulo="Ganho desde a compra" valor={reais(t.ganho)} detalhe={pct(t.ganho_pct)} cor={corValor(t.ganho)} />
      <Card titulo="Ganho no dia" valor={reais(t.ganho_dia)} cor={corValor(t.ganho_dia)} />
      <Card titulo="Ibovespa no mesmo período" valor={pct(t.ibovespa_desde_inicio)} cor={corValor(t.ibovespa_desde_inicio)}
            detalhe={`desde ${t.inicio || "–"} (BOVA11)`} />
    </div>
  );
}

function Indicacoes({ d, abrirAtivo }) {
  const bloco = (titulo, cor, itens, campo) => (
    <div>
      <h3 className={`font-semibold mt-3 ${cor}`}>{titulo} ({itens.length})</h3>
      {itens.map((i) => (
        <p key={i.ticker} className="text-sm cursor-pointer hover:underline" onClick={() => abrirAtivo(i.ticker)}>
          <b>{i.ticker}</b> #{i[campo] ?? "–"} — <span className="text-apagado">{(i.fatores || []).slice(0, 3).map((f) => f.texto).join("; ")}</span>
        </p>
      ))}
    </div>
  );
  return (
    <div className="bg-painel border border-borda rounded-lg p-3 max-h-[28rem] overflow-auto">
      <p className="text-xs text-apagado">Ranking de {d.ranking?.data}{d.ranking?.provisorio ? " (provisório)" : ""}. {d.regra}</p>
      {bloco("Considerar vender", "text-baixa", d.vender, "posicao_ranking")}
      {bloco("Observar", "text-atencao", d.observar, "posicao_ranking")}
      {bloco("Comprar (top 30 fora da carteira)", "text-alta", d.comprar, "posicao")}
      {d.sem_leitura.length > 0 && <p className="text-xs text-apagado mt-2">Sem leitura do modelo: {d.sem_leitura.map((p) => p.ticker).join(", ")}</p>}
      <p className="text-xs text-apagado mt-2 italic">{d.aviso}</p>
    </div>
  );
}

function NovaOperacao({ aoSalvar }) {
  const hoje = new Date().toISOString().slice(0, 10);
  const [op, setOp] = useState({ ticker: "", tipo: "compra", data: hoje, quantidade: "", preco: "", custos: "0" });
  const [msg, setMsg] = useState(null);
  const campo = (k, props = {}) => (
    <input value={op[k]} onChange={(e) => setOp({ ...op, [k]: e.target.value })} required
           className="bg-fundo border border-borda rounded px-2 py-1 w-28" {...props} />
  );
  const salvar = async (e) => {
    e.preventDefault();
    try {
      await chamar("/carteira/operacao", { metodo: "POST", corpo: { ...op, quantidade: Number(op.quantidade),
        preco: Number(String(op.preco).replace(",", ".")), custos: Number(String(op.custos).replace(",", ".")) } });
      setMsg("Operação registrada.");
      setOp({ ...op, ticker: "", quantidade: "", preco: "" });
      aoSalvar();
    } catch (err) {
      setMsg(`Erro: ${err.message}`);
    }
  };
  return (
    <form onSubmit={salvar} className="flex flex-wrap gap-2 items-center text-sm">
      {campo("ticker", { placeholder: "PETR4" })}
      <select value={op.tipo} onChange={(e) => setOp({ ...op, tipo: e.target.value })} className="bg-fundo border border-borda rounded px-2 py-1">
        <option value="compra">compra</option><option value="venda">venda</option>
      </select>
      {campo("data", { type: "date", max: hoje, className: "bg-fundo border border-borda rounded px-2 py-1" })}
      {campo("quantidade", { placeholder: "Qtd", inputMode: "numeric" })}
      {campo("preco", { placeholder: "Preço", inputMode: "decimal" })}
      {campo("custos", { placeholder: "Custos", inputMode: "decimal" })}
      <button className="bg-borda hover:bg-destaque/40 rounded px-3 py-1">Registrar</button>
      {msg && <span className="text-apagado">{msg}</span>}
    </form>
  );
}

export default function Carteira({ aoEnvelope, abrirAtivo }) {
  const cart = useApi("/carteira", { aoEnvelope });
  const ind = useApi("/carteira/indicacoes");
  const evol = useApi("/carteira/evolucao");
  const [msg, setMsg] = useState(null);
  const recarregar = () => { cart.recarregar(); ind.recarregar(); evol.recarregar(); };

  const importar = async (e) => {
    const arquivo = e.target.files[0];
    e.target.value = "";
    if (!arquivo) return;
    try {
      const r = await chamar("/carteira/importar", { metodo: "POST", arquivo });
      const ruins = r.nao_reconhecidas.slice(0, 10).map((x) => `linha ${x.linha}: ${x.motivo}`).join(" · ");
      setMsg(`${r.importadas} operações novas, ${r.ja_existiam} já existiam.${ruins ? ` Não reconhecidas: ${ruins}` : ""}`);
      recarregar();
    } catch (err) {
      setMsg(`Importação: ${err.message}`);
    }
  };
  const sincronizar = async () => {
    try {
      const r = await chamar("/carteira/sincronizar", { metodo: "POST" });
      setMsg(`${r.posicoes} posições sincronizadas da XP.`);
      recarregar();
    } catch (err) {
      setMsg(`XP: ${err.message}`);
    }
  };

  if (!cart.dados) return cart.erro ? <Erro erro={cart.erro} /> : <Carregando />;
  const d = cart.dados;
  const fonte = d.posicoes.length === 0
    ? "carteira vazia: registre uma operação, importe o extrato da B3/XP ou sincronize a XP (Meu Pluggy)"
    : d.sincronizada_em ? `XP sincronizada ${hora(d.sincronizada_em)}` : "operações registradas";
  return (
    <div className="space-y-3">
      <Erro erro={cart.erro} />
      <ResumoCarteira dados={d} />
      <div className="flex flex-wrap gap-3 items-center text-sm">
        <label className="bg-borda hover:bg-destaque/40 rounded px-3 py-1 cursor-pointer">
          Importar extrato…<input type="file" accept=".csv,.xlsx,.xls" onChange={importar} className="hidden" />
        </label>
        <button onClick={sincronizar} className="bg-borda hover:bg-destaque/40 rounded px-3 py-1">Sincronizar XP</button>
        <span className="text-apagado">Fonte: {fonte}</span>
      </div>
      {msg && <p className="text-sm text-atencao">{msg}</p>}
      {d.avisos.length > 0 && <p className="text-sm text-atencao">⚠ {d.avisos.join(" · ")}</p>}
      <NovaOperacao aoSalvar={recarregar} />
      <Tabela colunas={COLUNAS_CARTEIRA} aoClicar={(l) => abrirAtivo(l.ticker)}
              linhas={d.posicoes.map((p) => ({ ...p, lucro_venda: p.vender_agora?.lucro, ir_venda: p.vender_agora?.ir_se_tributado }))}
              ordemInicial={{ chave: "valor", asc: false }} />
      <p className="text-xs text-apagado">IR (estimativa simplificada, não é orientação fiscal): vendas de ações até R$ 20 mil no mês
        são isentas; acima disso, 15% sobre o lucro. FII, ETF e BDR têm regras próprias.</p>
      <div className="grid lg:grid-cols-2 gap-3">
        {ind.dados ? <Indicacoes d={ind.dados} abrirAtivo={abrirAtivo} /> : <Carregando />}
        <div className="h-[28rem] bg-painel border border-borda rounded-lg p-2">
          <p className="text-xs text-apagado">Patrimônio × investido (R$)</p>
          <ResponsiveContainer height="94%">
            <LineChart data={evol.dados || []}>
              <XAxis dataKey="data" stroke="#8b949e" fontSize={11} minTickGap={40} />
              <YAxis stroke="#8b949e" fontSize={11} tickFormatter={(v) => num(v, 0)} />
              <Tooltip contentStyle={{ background: "#161b22", border: "1px solid #30363d" }} formatter={(v) => reais(v)} />
              <Legend />
              <Line name="Patrimônio" dataKey="valor" stroke="#58a6ff" dot={false} strokeWidth={2} isAnimationActive={false} />
              <Line name="Investido" dataKey="investido" stroke="#8b949e" dot={false} strokeDasharray="4 4" isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
      <Aviso />
    </div>
  );
}
