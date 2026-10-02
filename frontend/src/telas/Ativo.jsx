import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { chamar, useApi } from "../api.js";
import { Aviso, Carregando, Erro, Tabela } from "../comum.jsx";
import { corValor, hora, num, pct, reais } from "../fmt.js";

const PERIODOS = [["1 mês", 31], ["3 meses", 92], ["1 ano", 365], ["3 anos", 1095], ["5 anos", 1825]];
const EIXO = { stroke: "#8b949e", fontSize: 11 };
const DICA = { background: "#161b22", border: "1px solid #30363d" };

function Porque({ ticker, fatores, logado }) {
  const [estado, setEstado] = useState({ texto: null, carregando: false, erro: null });
  const pedir = async () => {
    setEstado({ texto: null, carregando: true, erro: null });
    try {
      const r = await chamar(`/ativo/${ticker}/porque`);
      setEstado({ texto: r.dados, carregando: false, erro: null });
    } catch (e) {
      setEstado({ texto: null, carregando: false, erro: e });
    }
  };
  const d = estado.texto;
  return (
    <div className="space-y-2 text-sm">
      <p className="text-apagado">Fatores que mais pesaram:</p>
      <ul className="list-disc pl-5">{(fatores || []).map((f) => <li key={f.sinal}>{f.texto}</li>)}</ul>
      {d && (
        <div className="bg-fundo border border-borda rounded p-2">
          <p>{d.texto}</p>
          {d.numeros_nao_verificados.length > 0 && (
            <p className="text-atencao">⚠ números não verificados: {d.numeros_nao_verificados.join(", ")}</p>
          )}
        </div>
      )}
      {estado.erro && <p className="text-atencao">Explicação indisponível: {estado.erro.message}</p>}
      {!logado && <p className="text-apagado">Entre (no topo da página) para usar a explicação com IA.</p>}
      <button onClick={pedir} disabled={estado.carregando || !logado}
              className="bg-borda hover:bg-destaque/40 rounded px-3 py-1.5 disabled:opacity-50">
        {estado.carregando ? "Pedindo…" : "Explicar com IA"}
      </button>
    </div>
  );
}

export default function Ativo({ ticker, aoEnvelope, abrirAtivo, logado }) {
  const [dias, setDias] = useState(365);
  const [entrada, setEntrada] = useState("");
  const [aba, setAba] = useState("porque");
  const { dados, erro } = useApi(ticker ? `/ativo/${ticker}?dias=${dias}` : null, { aoEnvelope });

  const busca = (
    <form className="flex gap-2 mb-3" onSubmit={(e) => { e.preventDefault(); if (entrada.trim()) abrirAtivo(entrada.trim().toUpperCase()); }}>
      <input value={entrada} onChange={(e) => setEntrada(e.target.value)} placeholder="Ticker (ex.: PETR4)"
             className="bg-painel border border-borda rounded px-3 py-1.5 w-44" />
      <select value={dias} onChange={(e) => setDias(Number(e.target.value))} className="bg-painel border border-borda rounded px-2">
        {PERIODOS.map(([r, d]) => <option key={d} value={d}>{r}</option>)}
      </select>
    </form>
  );
  if (!ticker) return <div>{busca}<p className="text-apagado">Escolha uma ação.</p></div>;
  if (!dados) return <div>{busca}{erro ? <Erro erro={erro} /> : <Carregando />}</div>;

  const c = dados.cotacao || {};
  const r = dados.ranking;
  const precos = dados.precos.filter((p) => p.fechamento).map((p) => ({ data: p.data, preco: p.fechamento }));
  return (
    <div>
      {busca}
      <Erro erro={erro} />
      <h1 className="text-lg font-semibold mb-3">
        {dados.ticker} · {dados.nome} · {reais(c.preco)} <span className={corValor(c.variacao_dia)}>{pct(c.variacao_dia)}</span>
        {" · "}{r.posicao ? `#${r.posicao} de ${r.total} (score ${num(r.score, 3)})` : "fora do ranking"}
        <span className="text-apagado text-sm"> · às {hora(c.horario)}</span>
        {c.provisorio && <span className="ml-2 text-xs bg-atencao text-fundo rounded px-1.5 py-0.5">PROVISÓRIO</span>}
      </h1>
      <div className="grid lg:grid-cols-5 gap-3">
        <div className="lg:col-span-3 space-y-3">
          <div className="h-72 bg-painel border border-borda rounded-lg p-2">
            <p className="text-xs text-apagado">Preço (ajustado por desdobramentos)</p>
            <ResponsiveContainer height="92%">
              <LineChart data={precos}>
                <CartesianGrid stroke="#21262d" />
                <XAxis dataKey="data" {...EIXO} minTickGap={40} />
                <YAxis {...EIXO} domain={["auto", "auto"]} tickFormatter={(v) => num(v, 0)} />
                <Tooltip contentStyle={DICA} formatter={(v) => reais(v)} />
                <Line dataKey="preco" stroke="#58a6ff" dot={false} strokeWidth={2} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="h-52 bg-painel border border-borda rounded-lg p-2">
            <p className="text-xs text-apagado">Posição no ranking (1 = topo)</p>
            <ResponsiveContainer height="88%">
              <LineChart data={dados.historico_score}>
                <XAxis dataKey="data" {...EIXO} minTickGap={40} />
                <YAxis {...EIXO} reversed domain={[1, "auto"]} />
                <Tooltip contentStyle={DICA} />
                <Line dataKey="posicao" stroke="#d29922" dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="lg:col-span-2 bg-painel border border-borda rounded-lg p-3">
          <div className="flex gap-2 mb-3 text-sm">
            {[["porque", "Por quê"], ["sinais", "Sinais"], ["noticias", "Notícias e fatos"]].map(([k, t]) => (
              <button key={k} onClick={() => setAba(k)}
                      className={`px-3 py-1 rounded ${aba === k ? "bg-destaque/30" : "bg-borda/50"}`}>{t}</button>
            ))}
          </div>
          {aba === "porque" && <Porque ticker={dados.ticker} fatores={dados.fatores} logado={logado} />}
          {aba === "sinais" && (
            <Tabela chaveLinha="sinal" linhas={dados.sinais.sinais} colunas={[
              { titulo: "Sinal", chave: "nome" },
              { titulo: "Valor", chave: "valor", fmt: (v) => num(v, 3) },
              { titulo: "Percentil", chave: "percentil", fmt: (v) => (v === null ? "–" : String(Math.round(v * 100))) },
              { titulo: "Nível", chave: "nivel" },
            ]} />
          )}
          {aba === "noticias" && (
            <div className="text-sm space-y-2 max-h-[32rem] overflow-auto">
              <h3 className="font-semibold">Fatos relevantes</h3>
              {dados.fatos_relevantes.map((f, i) => (
                <p key={i}><b>{f.data}</b> · {f.evento || ""} ({f.direcao || "sem classificação"})<br />
                  {f.resumo || f.assunto} {f.url && <a className="text-destaque" href={f.url} target="_blank" rel="noreferrer">documento</a>}</p>
              ))}
              <h3 className="font-semibold pt-2">Notícias</h3>
              {dados.noticias.map((n) => (
                <p key={n.url}><span className={corValor(n.sentimento) || "text-apagado"}>●</span> {hora(n.disponivel_em)} · {n.fonte} ·{" "}
                  <a className="text-destaque" href={n.url} target="_blank" rel="noreferrer">{n.titulo}</a></p>
              ))}
            </div>
          )}
        </div>
      </div>
      <Aviso />
    </div>
  );
}
