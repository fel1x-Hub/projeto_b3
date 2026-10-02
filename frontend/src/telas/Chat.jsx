import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { chamar, useApi } from "../api.js";
import { Aviso } from "../comum.jsx";

export default function Chat() {
  // Histórico só da sessão (não persiste entre recargas, etapa 7.4)
  const [mensagens, setMensagens] = useState([]);
  const [texto, setTexto] = useState("");
  const [esperando, setEsperando] = useState(false);
  const [erro, setErro] = useState(null);
  const sugestoes = useApi("/chat/sugestoes");
  const fim = useRef(null);
  useEffect(() => { fim.current?.scrollIntoView?.({ behavior: "smooth" }); }, [mensagens, esperando]);

  const enviar = async (pergunta) => {
    const t = (pergunta ?? texto).trim();
    if (!t || esperando) return;
    const nova = [...mensagens, { papel: "usuario", texto: t }];
    setMensagens(nova);
    setTexto("");
    setErro(null);
    setEsperando(true);
    try {
      const r = await chamar("/chat", { metodo: "POST", corpo: { mensagens: nova.map(({ papel, texto: x }) => ({ papel, texto: x })) } });
      setMensagens([...nova, { papel: "assistente", texto: r.dados.resposta, avisos: r.dados.numeros_nao_verificados }]);
    } catch (e) {
      setMensagens(mensagens);
      setErro(e);
    } finally {
      setEsperando(false);
    }
  };

  return (
    <div className="flex flex-col h-[78vh]">
      <div className="flex-1 overflow-auto cartao p-4 space-y-4">
        {mensagens.length === 0 && <p className="text-apagado">Pergunte sobre ações, o ranking ou sua carteira.</p>}
        {mensagens.map((m, i) => (
          <div key={i}>
            <b className={m.papel === "usuario" ? "text-destaque-escuro" : "text-texto"}>{m.papel === "usuario" ? "Você" : "Assistente"}:</b>
            <div className="markdown">{m.papel === "usuario" ? <p>{m.texto}</p> : <Markdown>{m.texto}</Markdown>}</div>
            {m.avisos?.length > 0 && <p className="text-atencao text-sm">⚠ números não verificados: {m.avisos.join(", ")}</p>}
          </div>
        ))}
        {esperando && <p className="text-apagado">pensando…</p>}
        {erro && <p className="text-baixa">Não deu para responder agora: {erro.message}</p>}
        <div ref={fim} />
      </div>
      <div className="flex flex-wrap gap-2 my-2">
        {(sugestoes.dados || []).slice(0, 4).map((s) => (
          <button key={s} onClick={() => enviar(s)} className="btn-secundario text-xs">{s}</button>
        ))}
      </div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); enviar(); }}>
        <input value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Sua pergunta…"
               className="campo flex-1" />
        <button disabled={esperando} className="btn-primario">Enviar</button>
      </form>
      <Aviso />
    </div>
  );
}
