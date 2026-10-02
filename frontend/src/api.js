// Acesso à API (regra 10: o site só fala com a API). Guarda só a sessão de login (nunca a senha).
import { useCallback, useEffect, useRef, useState } from "react";

export const BASE = import.meta.env.VITE_API_URL || "/api";
const CHAVE = "projeto_b3_token";
const ABERTO_MS = 60_000;
const FECHADO_MS = 300_000;

export const token = {
  ler: () => { try { return localStorage.getItem(CHAVE) || ""; } catch { return ""; } },
  gravar: (t) => { try { localStorage.setItem(CHAVE, t); } catch { /* sem storage: vale só nesta aba */ } },
  apagar: () => { try { localStorage.removeItem(CHAVE); } catch { /* idem */ } },
};

export class ErroAPI extends Error {
  constructor(msg, status) { super(msg); this.status = status; }
}

export async function chamar(caminho, { metodo = "GET", corpo, arquivo } = {}) {
  const sessao = token.ler();          // visitante não manda nada; quem entrou manda a sessão
  const opcoes = { method: metodo, headers: sessao ? { Authorization: `Bearer ${sessao}` } : {} };
  if (arquivo) {
    const form = new FormData();
    form.append("arquivo", arquivo);
    opcoes.body = form;
  } else if (corpo !== undefined) {
    opcoes.headers["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }
  const r = await fetch(BASE + caminho, opcoes);
  const json = await r.json().catch(() => ({}));
  if (!r.ok) {
    const det = json.detail;
    throw new ErroAPI(typeof det === "string" ? det : JSON.stringify(det ?? r.statusText), r.status);
  }
  return json;
}

/** Busca e se atualiza sozinho (regra 15). Em falha, mantém o último dado válido e expõe o erro. */
export function useApi(caminho, { ativo = true, aoEnvelope } = {}) {
  const [estado, setEstado] = useState({ env: null, dados: null, erro: null, carregando: true });
  const intervalo = useRef(ABERTO_MS);
  const envRef = useRef(aoEnvelope);
  envRef.current = aoEnvelope;

  const buscar = useCallback(async () => {
    if (!caminho) return;
    try {
      const env = await chamar(caminho);
      intervalo.current = env.mercado_aberto ? ABERTO_MS : FECHADO_MS;
      setEstado({ env, dados: env.dados, erro: null, carregando: false });
      envRef.current?.(env);
    } catch (e) {
      setEstado((s) => ({ ...s, erro: e, carregando: false }));
      envRef.current?.(null, e);
    }
  }, [caminho]);

  useEffect(() => {
    if (!ativo || !caminho) return undefined;
    let vivo = true;
    let timer;
    const ciclo = async () => {
      await buscar();
      if (vivo) timer = setTimeout(ciclo, intervalo.current);
    };
    setEstado((s) => ({ ...s, carregando: true }));
    ciclo();
    return () => { vivo = false; clearTimeout(timer); };
  }, [caminho, ativo, buscar]);

  return { ...estado, recarregar: buscar };
}
