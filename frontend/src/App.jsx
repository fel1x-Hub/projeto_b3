import { useCallback, useState } from "react";
import { chamar, token } from "./api.js";
import { hora } from "./fmt.js";
import Ativo from "./telas/Ativo.jsx";
import Carteira from "./telas/Carteira.jsx";
import Chat from "./telas/Chat.jsx";
import Mercado from "./telas/Mercado.jsx";
import Ranking from "./telas/Ranking.jsx";
import Relatorio from "./telas/Relatorio.jsx";

const ABAS = [["mercado", "Mercado"], ["ranking", "Ranking"], ["ativo", "Ação"], ["carteira", "Carteira"],
              ["relatorio", "Relatório"], ["chat", "Chat IA"]];

function Entrar({ aoEntrar }) {
  const [valor, setValor] = useState("");
  const [erro, setErro] = useState(null);
  const entrar = async (e) => {
    e.preventDefault();
    token.gravar(valor.trim());
    try {
      await chamar("/status");
      aoEntrar();
    } catch (err) {
      token.apagar();
      setErro(err.status === 401 ? "Token inválido." : `API indisponível: ${err.message}`);
    }
  };
  return (
    <form onSubmit={entrar} className="max-w-md mx-auto mt-24 bg-painel border border-borda rounded-lg p-6 space-y-3">
      <h1 className="text-xl font-semibold">Projeto B3</h1>
      <p className="text-sm text-apagado">Cole o API_TOKEN do seu .env (fica guardado só neste navegador).</p>
      <input type="password" value={valor} onChange={(e) => setValor(e.target.value)} autoFocus
             className="w-full bg-fundo border border-borda rounded px-3 py-2" placeholder="API_TOKEN" />
      {erro && <p className="text-baixa text-sm">{erro}</p>}
      <button className="bg-destaque/60 hover:bg-destaque rounded px-4 py-2">Entrar</button>
    </form>
  );
}

export default function App() {
  const [logado, setLogado] = useState(Boolean(token.ler()));
  const [aba, setAba] = useState("mercado");
  const [ticker, setTicker] = useState(null);
  const [status, setStatus] = useState({ env: null, erro: null });

  const aoEnvelope = useCallback((env, erro) => {
    if (erro?.status === 401) { token.apagar(); setLogado(false); return; }
    setStatus((s) => (env ? { env, erro: null } : { env: s.env, erro }));
  }, []);
  const abrirAtivo = useCallback((t) => { setTicker(t); setAba("ativo"); }, []);

  if (!logado) return <Entrar aoEntrar={() => setLogado(true)} />;
  const env = status.env;
  const props = { aoEnvelope, abrirAtivo };
  return (
    <div className="min-h-screen flex flex-col">
      <nav className="flex flex-wrap gap-1 border-b border-borda px-3 pt-2 bg-painel">
        <span className="font-semibold mr-4 self-center">Projeto B3</span>
        {ABAS.map(([k, t]) => (
          <button key={k} onClick={() => setAba(k)}
                  className={`px-4 py-2 rounded-t text-sm ${aba === k ? "bg-fundo border border-b-0 border-borda" : "text-apagado hover:text-texto"}`}>
            {t}
          </button>
        ))}
      </nav>
      <main className="flex-1 p-4">
        {aba === "mercado" && <Mercado {...props} />}
        {aba === "ranking" && <Ranking {...props} />}
        {aba === "ativo" && <Ativo ticker={ticker} {...props} />}
        {aba === "carteira" && <Carteira {...props} />}
        {aba === "relatorio" && <Relatorio {...props} />}
        {aba === "chat" && <Chat />}
      </main>
      <footer className="flex flex-wrap justify-end gap-4 items-center text-xs px-3 py-1.5 border-t border-borda bg-painel" data-testid="status">
        {status.erro && <span className="text-atencao mr-auto">⚠ Falha ao atualizar: {status.erro.message} — mostrando o último dado válido</span>}
        {env && <span className={env.mercado_aberto ? "text-alta" : "text-apagado"}>{env.mercado_aberto ? "● Pregão aberto" : "○ Mercado fechado"}</span>}
        {env?.atualizado_em && <span>dados de {hora(env.atualizado_em)}</span>}
        {env?.provisorio && <span className="bg-atencao text-fundo font-semibold rounded px-1.5"
                                  title="Valor intradiário (~15 min de atraso); o oficial sai depois do fechamento">PROVISÓRIO</span>}
        <button className="text-apagado hover:text-texto" onClick={() => { token.apagar(); setLogado(false); }}>sair</button>
      </footer>
    </div>
  );
}
