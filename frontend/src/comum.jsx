import { useMemo, useState } from "react";
import { AVISO } from "./fmt.js";

export function Card({ titulo, valor, detalhe, cor = "" }) {
  return (
    <div className="cartao p-4 min-w-0">
      <div className="text-xs font-semibold uppercase tracking-wide text-apagado">{titulo}</div>
      <div className={`text-2xl font-extrabold truncate mt-1 ${cor}`}>{valor}</div>
      <div className="text-xs text-apagado truncate">{detalhe}</div>
    </div>
  );
}

export const Aviso = () => <p className="text-xs text-apagado mt-3">{AVISO}</p>;

export function Erro({ erro }) {
  if (!erro) return null;
  return <p className="text-atencao text-sm my-2">⚠ Falha ao atualizar: {erro.message}. Mostrando o último dado válido.</p>;
}

export const Carregando = () => <p className="text-apagado p-4">Carregando…</p>;

/** Tabela ordenável. colunas: [{titulo, chave, fmt?, colorir?}] */
export function Tabela({ colunas, linhas, chaveLinha = "ticker", aoClicar, ordemInicial }) {
  const [ordem, setOrdem] = useState(ordemInicial || { chave: colunas[0].chave, asc: true });
  const ordenadas = useMemo(() => {
    const v = [...(linhas || [])];
    v.sort((a, b) => {
      const x = a[ordem.chave];
      const y = b[ordem.chave];
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : 1) * (ordem.asc ? 1 : -1);
    });
    return v;
  }, [linhas, ordem]);
  const cor = (c, v) => (c.colorir ? (v > 0 ? "text-alta" : v < 0 ? "text-baixa" : "") : "");
  return (
    <div className="cartao overflow-auto">
      <table className="w-full text-sm">
        <thead className="bg-fundo sticky top-0 text-apagado text-xs uppercase tracking-wide">
          <tr>
            {colunas.map((c) => (
              <th key={c.chave} className="px-3 py-2.5 text-left font-semibold cursor-pointer select-none whitespace-nowrap hover:text-texto"
                  onClick={() => setOrdem((o) => ({ chave: c.chave, asc: o.chave === c.chave ? !o.asc : true }))}>
                {c.titulo}{ordem.chave === c.chave ? (ordem.asc ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ordenadas.map((l) => (
            <tr key={l[chaveLinha]} onClick={() => aoClicar?.(l)}
                className={`border-t border-borda ${aoClicar ? "cursor-pointer hover:bg-suave" : ""}`}>
              {colunas.map((c) => (
                <td key={c.chave} className={`px-3 py-2 whitespace-nowrap ${c.fmt ? "text-right tabular-nums" : ""} ${cor(c, l[c.chave])}`}>
                  {c.fmt ? c.fmt(l[c.chave]) : (l[c.chave] ?? "–")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
