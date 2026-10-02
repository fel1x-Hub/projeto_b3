import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useApi } from "../api.js";
import { ResumoCarteira } from "./Carteira.jsx";
import { TabelaRanking } from "./Ranking.jsx";

const LINHAS = [
  { posicao: 2, ticker: "VALE3", nome: "Vale", score: 0.55, preco: 70.3, variacao_dia: -0.01, na_carteira: false },
  { posicao: 1, ticker: "PETR4", nome: "Petrobras", score: 0.6, preco: 49.77, variacao_dia: 0.0132, na_carteira: true },
];

describe("TabelaRanking", () => {
  it("ordena pela posição, formata em pt-BR, colore e abre o ativo", () => {
    const abrir = vi.fn();
    render(<TabelaRanking linhas={LINHAS} abrirAtivo={abrir} />);
    const linhas = screen.getAllByRole("row").slice(1);
    expect(linhas[0]).toHaveTextContent("PETR4");
    expect(screen.getByText("R$ 49,77")).toBeInTheDocument();
    expect(screen.getByText("+1,32%")).toHaveClass("text-alta");
    expect(screen.getByText("-1,00%")).toHaveClass("text-baixa");
    fireEvent.click(linhas[1]);
    expect(abrir).toHaveBeenCalledWith("VALE3");
  });

  it("filtra por nome e reordena ao clicar no cabeçalho", () => {
    const { rerender } = render(<TabelaRanking linhas={LINHAS} filtro="vale" abrirAtivo={() => {}} />);
    expect(screen.getAllByRole("row")).toHaveLength(2);
    rerender(<TabelaRanking linhas={LINHAS} filtro="" abrirAtivo={() => {}} />);
    fireEvent.click(screen.getByText(/^#/));                 // inverte: maior posição primeiro
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("VALE3");
  });
});

describe("ResumoCarteira", () => {
  it("mostra valor, ganho com cor e comparação com o Ibovespa", () => {
    render(<ResumoCarteira dados={{ totais: { valor: 4977, custo: 3010, ganho: 1967, ganho_pct: 0.6535,
      ganho_dia: -12.5, inicio: "2026-01-05", ibovespa_desde_inicio: 0.1719 } }} />);
    expect(screen.getByText("R$ 4.977,00")).toBeInTheDocument();
    expect(screen.getByText("R$ 1.967,00")).toHaveClass("text-alta");
    expect(screen.getByText("R$ -12,50")).toHaveClass("text-baixa");
    expect(screen.getByText("+17,19%")).toBeInTheDocument();
    expect(screen.getByText("+65,35%")).toBeInTheDocument();
  });
});

describe("useApi (regra 15)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("mantém o último dado válido quando a API falha", async () => {
    const respostas = [
      { ok: true, json: async () => ({ dados: { x: 1 }, mercado_aberto: true, atualizado_em: "t" }) },
      { ok: false, status: 503, statusText: "x", json: async () => ({ detail: "fora do ar" }) },
    ];
    vi.stubGlobal("fetch", vi.fn(async () => respostas.shift()));
    const { result } = renderHook(() => useApi("/mercado"));
    await waitFor(() => expect(result.current.dados).toEqual({ x: 1 }));
    await act(() => result.current.recarregar());
    expect(result.current.dados).toEqual({ x: 1 });
    expect(result.current.erro.message).toBe("fora do ar");
  });
});
