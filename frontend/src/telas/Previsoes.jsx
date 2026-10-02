import { corValor, pct } from "../fmt.js";

const COR_SINAL = { compra: "text-alta", venda: "text-baixa" };
const COR_TEND = { alta: "text-alta", baixa: "text-baixa", lateral: "text-apagado" };

export function Nota({ rotulo, valor, cor }) {
  return (
    <div className="bg-suave rounded-2xl px-5 py-3 text-center min-w-32">
      <div className="text-xs text-apagado">{rotulo}</div>
      <div className={`text-4xl font-extrabold ${cor}`}>{valor ?? "–"}</div>
      <div className="text-xs text-apagado">de 0 a 100</div>
    </div>
  );
}

/** Pontuações, tendência, padrão gráfico e o histórico da faixa em cada prazo (não é promessa). */
export default function Previsoes({ pontuacao, previsoes, padrao }) {
  const tend = padrao?.tendencia;
  const graf = padrao?.grafico;
  return (
    <div className="cartao p-4 mb-3 space-y-3">
      <div className="flex flex-wrap gap-3 items-center">
        <Nota rotulo="Nota de compra" valor={pontuacao?.compra} cor="text-destaque-escuro" />
        <div className="text-sm space-y-1">
          <div>Tendência do preço: {tend ? <b className={COR_TEND[tend.tendencia]}>{tend.tendencia}</b> : "–"}
            {tend && <span className="text-apagado"> (preço {tend.acima_mm50 ? "acima" : "abaixo"} da média de 50 dias e {tend.acima_mm200 ? "acima" : "abaixo"} da de 200; 3 meses {pct(tend.retorno_3m)})</span>}
          </div>
          <div>Padrão gráfico: {graf ? <b>{graf.nome}</b> : <span className="text-apagado">nenhum padrão clássico confirmado nos últimos 120 pregões</span>}
            {graf && <span className="text-apagado"> (leitura clássica: {graf.direcao_classica})</span>}
          </div>
          {graf?.efeito_historico?.map((e) => <div key={e.horizonte} className="text-xs text-apagado">↳ {e.conclusao}</div>)}
        </div>
      </div>
      {previsoes?.length > 0 && (
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-apagado text-left text-xs uppercase tracking-wide">
              <th className="py-1">Prazo</th><th>Ganho esperado*</th><th>Faixa provável</th><th>Contra o mercado</th>
              <th>Chance de superar</th><th>Sinal</th><th>Comportamento</th>
            </tr></thead>
            <tbody>
              {previsoes.map((p) => (
                <tr key={p.horizonte} className="border-t border-borda">
                  <td className="py-1">{p.prazo}</td>
                  <td className={corValor(p.retorno_medio)}>{pct(p.retorno_medio, 1)}</td>
                  <td>{pct(p.p25, 0)} a {pct(p.p75, 0)}</td>
                  <td className={corValor(p.excesso_medio)}>{pct(p.excesso_medio, 1)}</td>
                  <td>{pct(p.chance_superar, 0, false)}</td>
                  <td className={COR_SINAL[p.sinal] || "text-apagado"}>{p.sinal}</td>
                  <td className="text-apagado">{p.comportamento}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-apagado mt-1">
            Não é promessa: é o que aconteceu, fora da amostra, com ações na mesma faixa de pontuação
            ({previsoes[0].faixa_min}–{previsoes[0].faixa_max}) entre {previsoes[0].periodo_inicio} e {previsoes[0].periodo_fim}.
            Sinal só com evidência estatística; prazos longos têm pouco histórico.
          </p>
        </div>
      )}
    </div>
  );
}
