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
    <form onSubmit={entrar} className="cartao max-w-sm mx-auto mt-16 p-8 space-y-4">
      <h1 className="text-2xl font-extrabold">Entrar</h1>
      {motivo && <p className="text-sm text-apagado">{motivo}</p>}
      <input value={usuario} onChange={(e) => setUsuario(e.target.value)} autoFocus autoComplete="username"
             className="campo w-full" placeholder="Usuário" />
      <input type="password" value={senha} onChange={(e) => setSenha(e.target.value)} autoComplete="current-password"
             className="campo w-full" placeholder="Senha" />
      {erro && <p className="text-baixa text-sm">{erro}</p>}
      <button disabled={enviando || !usuario || !senha} className="btn-primario w-full">
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
      <header className="bg-painel border-b border-borda shadow-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 flex flex-wrap items-center gap-x-6">
          <span className="flex items-center gap-2 py-3 mr-2">
            <span className="w-8 h-8 rounded-lg bg-destaque text-white font-extrabold grid place-items-center">B3</span>
            <span className="font-extrabold text-lg">Projeto B3</span>
          </span>
          <nav className="flex flex-wrap gap-1 self-stretch">
            {ABAS.map(([k, t]) => (
              <button key={k} onClick={() => setAba(k)}
                      className={`px-3 text-sm font-semibold border-b-[3px] transition-colors ${aba === k
                        ? "border-destaque text-texto" : "border-transparent text-apagado hover:text-texto"}`}>
                {t}
              </button>
            ))}
          </nav>
          <span className="ml-auto text-sm py-3">
            {logado
              ? <span className="flex items-center gap-3"><span className="font-semibold">{usuario}</span>
                  <button className="btn-secundario text-xs" onClick={sair}>sair</button></span>
              : <button className="btn-primario text-sm" onClick={() => setAba("carteira")}>Entrar</button>}
          </span>
        </div>
      </header>
      <main className="flex-1 w-full max-w-7xl mx-auto p-4">
        {aba === "mercado" && <Mercado {...props} />}
        {aba === "ranking" && <Ranking {...props} />}
        {aba === "ativo" && <Ativo ticker={ticker} {...props} />}
        {aba === "carteira" && (logado ? <Carteira {...props} /> : pedirLogin("A carteira é pessoal: entre para ver e editar."))}
        {aba === "relatorio" && <Relatorio {...props} />}
        {aba === "chat" && (logado ? <Chat /> : pedirLogin("O chat de IA usa a sua cota do Gemini: entre para usar."))}
      </main>
      <footer className="flex flex-wrap justify-end gap-4 items-center text-xs px-4 py-2 border-t border-borda bg-painel" data-testid="status">
        <span className="mr-auto text-apagado">Projeto pessoal de estudo, sem vínculo com o Itaú Unibanco ou com a B3. Não é recomendação de investimento.</span>
        {status.erro && <span className="text-atencao">⚠ Falha ao atualizar: {status.erro.message} — mostrando o último dado válido</span>}
        {env && <span className={`font-semibold ${env.mercado_aberto ? "text-alta" : "text-apagado"}`}>{env.mercado_aberto ? "● Pregão aberto" : "○ Mercado fechado"}</span>}
        {env?.atualizado_em && <span>dados de {hora(env.atualizado_em)}</span>}
        {env?.provisorio && <span className="selo"
                                  title="Valor intradiário (~15 min de atraso); o oficial sai depois do fechamento">PROVISÓRIO</span>}
      </footer>
    </div>
  );
}
