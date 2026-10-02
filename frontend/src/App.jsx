import { useCallback, useEffect, useState } from "react";
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

/** Login por usuário e senha. A senha não fica guardada: só a sessão (vale 30 dias). */
export function Entrar({ aoEntrar, motivo }) {
  const [usuario, setUsuario] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const entrar = async (e) => {
    e.preventDefault();
    setEnviando(true);
    setErro(null);
    try {
      const r = await chamar("/login", { metodo: "POST", corpo: { usuario, senha } });
      token.gravar(r.sessao);
      aoEntrar(r.usuario);
    } catch (err) {
      setErro(err.status === 401 ? "Usuário ou senha incorretos." :
              err.status === 429 ? "Muitas tentativas. Espere um minuto." : `Não deu para entrar: ${err.message}`);
    } finally {
      setEnviando(false);
    }
  };
  return (
    <form onSubmit={entrar} className="max-w-sm mx-auto mt-16 bg-painel border border-borda rounded-lg p-6 space-y-3">
      <h1 className="text-xl font-semibold">Entrar</h1>
      {motivo && <p className="text-sm text-apagado">{motivo}</p>}
      <input value={usuario} onChange={(e) => setUsuario(e.target.value)} autoFocus autoComplete="username"
             className="w-full bg-fundo border border-borda rounded px-3 py-2" placeholder="Usuário" />
      <input type="password" value={senha} onChange={(e) => setSenha(e.target.value)} autoComplete="current-password"
             className="w-full bg-fundo border border-borda rounded px-3 py-2" placeholder="Senha" />
      {erro && <p className="text-baixa text-sm">{erro}</p>}
      <button disabled={enviando || !usuario || !senha}
              className="bg-destaque/60 hover:bg-destaque rounded px-4 py-2 disabled:opacity-50">
        {enviando ? "Entrando…" : "Entrar"}
      </button>
    </form>
  );
}

export default function App() {
  const [usuario, setUsuario] = useState(null);       // null = visitante (vê mercado, ranking, ações, relatório)
  const [aba, setAba] = useState("mercado");
  const [ticker, setTicker] = useState(null);
  const [status, setStatus] = useState({ env: null, erro: null });

  useEffect(() => {                                    // sessão guardada ainda vale?
    if (!token.ler()) return;
    chamar("/eu").then((r) => (r.logado ? setUsuario(r.usuario) : token.apagar())).catch(() => {});
  }, []);

  const sair = useCallback(() => { token.apagar(); setUsuario(null); }, []);
  const aoEnvelope = useCallback((env, erro) => {
    if (erro?.status === 401) { sair(); return; }    // sessão expirou: volta a visitante
    setStatus((s) => (env ? { env, erro: null } : { env: s.env, erro }));
  }, [sair]);
  const abrirAtivo = useCallback((t) => { setTicker(t); setAba("ativo"); }, []);

  const env = status.env;
  const logado = Boolean(usuario);
  const props = { aoEnvelope, abrirAtivo, logado };
  const pedirLogin = (motivo) => <Entrar aoEntrar={setUsuario} motivo={motivo} />;
  return (
    <div className="min-h-screen flex flex-col">
      <nav className="flex flex-wrap gap-1 border-b border-borda px-3 pt-2 bg-painel items-end">
        <span className="font-semibold mr-4 self-center">Projeto B3</span>
        {ABAS.map(([k, t]) => (
          <button key={k} onClick={() => setAba(k)}
                  className={`px-4 py-2 rounded-t text-sm ${aba === k ? "bg-fundo border border-b-0 border-borda" : "text-apagado hover:text-texto"}`}>
            {t}
          </button>
        ))}
        <span className="ml-auto self-center text-sm pb-1">
          {logado
            ? <>{usuario} · <button className="text-apagado hover:text-texto" onClick={sair}>sair</button></>
            : <button className="text-destaque hover:underline" onClick={() => setAba("carteira")}>Entrar</button>}
        </span>
      </nav>
      <main className="flex-1 p-4">
        {aba === "mercado" && <Mercado {...props} />}
        {aba === "ranking" && <Ranking {...props} />}
        {aba === "ativo" && <Ativo ticker={ticker} {...props} />}
        {aba === "carteira" && (logado ? <Carteira {...props} /> : pedirLogin("A carteira é pessoal: entre para ver e editar."))}
        {aba === "relatorio" && <Relatorio {...props} />}
        {aba === "chat" && (logado ? <Chat /> : pedirLogin("O chat de IA usa a sua cota do Gemini: entre para usar."))}
      </main>
      <footer className="flex flex-wrap justify-end gap-4 items-center text-xs px-3 py-1.5 border-t border-borda bg-painel" data-testid="status">
        {status.erro && <span className="text-atencao mr-auto">⚠ Falha ao atualizar: {status.erro.message} — mostrando o último dado válido</span>}
        {env && <span className={env.mercado_aberto ? "text-alta" : "text-apagado"}>{env.mercado_aberto ? "● Pregão aberto" : "○ Mercado fechado"}</span>}
        {env?.atualizado_em && <span>dados de {hora(env.atualizado_em)}</span>}
        {env?.provisorio && <span className="bg-atencao text-fundo font-semibold rounded px-1.5"
                                  title="Valor intradiário (~15 min de atraso); o oficial sai depois do fechamento">PROVISÓRIO</span>}
      </footer>
    </div>
  );
}
