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
            className="btn-secundario text-sm">{texto}</button>
  );
  return (
    <div>
      <Erro erro={erro} />
      <div className="flex justify-between items-center mb-3">
        {botao(dados.anterior, "◀ Anterior")}
        <span className="font-bold">Relatório de {dados.data}</span>
        {botao(dados.proximo || (data !== "ultimo" ? "ultimo" : null), "Próximo ▶")}
      </div>
      <article className="markdown cartao p-6 max-w-4xl">
        <Markdown>{dados.markdown}</Markdown>
      </article>
    </div>
  );
}
