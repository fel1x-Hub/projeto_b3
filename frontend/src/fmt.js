// Formatação no padrão brasileiro. Só formata: nenhum número é calculado aqui.
const FUSO = "America/Sao_Paulo";

export function num(x, casas = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  return x.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}

export function pct(x, casas = 2, sinal = true) {
  if (x === null || x === undefined) return "–";
  const s = num(x * 100, casas) + "%";
  return sinal && x > 0 ? "+" + s : s;
}

export const reais = (x) => (x === null || x === undefined ? "–" : "R$ " + num(x));

export function hora(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  const hoje = new Date().toLocaleDateString("pt-BR", { timeZone: FUSO });
  const dia = d.toLocaleDateString("pt-BR", { timeZone: FUSO });
  const hm = d.toLocaleTimeString("pt-BR", { timeZone: FUSO, hour: "2-digit", minute: "2-digit" });
  return dia === hoje ? hm : `${dia.slice(0, 5)} ${hm}`;
}

export const corValor = (x) => (x > 0 ? "text-alta" : x < 0 ? "text-baixa" : "");

export const AVISO = "Não é recomendação de investimento. Material de apoio; a decisão e a execução são suas.";
