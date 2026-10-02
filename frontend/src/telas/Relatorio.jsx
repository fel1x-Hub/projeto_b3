import { useState } from "react";
import Markdown from "react-markdown";
import { useApi } from "../api.js";
import { Carregando, Erro } from "../comum.jsx";

export default function Relatorio({ aoEnvelope }) {
  const [data, setData] = useState("ultimo");
  const { dados, erro } = useApi(`/relatorio/${data}`, { aoEnvelope });
  if (!dados) return erro ? <Erro erro={erro} /> : <Carregando />;
  const botao = (alvo, texto) => (
    <button disabled={!alvo} onClick={() => setData(alvo)}
            className="bg-borda hover:bg-destaque/40 rounded px-3 py-1 disabled:opacity-40">{texto}</button>
  );
  return (
    <div>
      <Erro erro={erro} />
      <div className="flex justify-between items-center mb-3">
        {botao(dados.anterior, "◀ Anterior")}
        <span className="text-sm">Relatório de {dados.data}</span>
        {botao(dados.proximo || (data !== "ultimo" ? "ultimo" : null), "Próximo ▶")}
      </div>
      <article className="markdown bg-painel border border-borda rounded-lg p-4 max-w-4xl">
        <Markdown>{dados.markdown}</Markdown>
      </article>
    </div>
  );
}
