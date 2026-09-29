# Avaliação do sentimento (29/09/2026)

- **Modelo:** `lucas-leme/FinBERT-PT-BR`, classificando o título.
- **Referência:** `rotulos/sentimento.csv`, com 100 notícias rotuladas por: claude. O critério está em `rotulos/README.md`.
- **Notícias sem classificação do modelo:** 0.

### Modelo

Acurácia **69.0%** · F1 macro **0.670** · n = 100

| Classe | Precisão | Revocação | F1 | Suporte |
|---|---|---|---|---|
| positivo | 0.77 | 0.53 | 0.62 | 19 |
| neutro | 0.90 | 0.64 | 0.75 | 58 |
| negativo | 0.48 | 0.96 | 0.64 | 23 |

### Linha de base (sempre 'neutro')

Acurácia **58.0%** · F1 macro **0.245** · n = 100

| Classe | Precisão | Revocação | F1 | Suporte |
|---|---|---|---|---|
| positivo | 0.00 | 0.00 | 0.00 | 19 |
| neutro | 0.58 | 1.00 | 0.73 | 58 |
| negativo | 0.00 | 0.00 | 0.00 | 23 |

### Matriz de confusão (linhas = referência, colunas = modelo)

| | positivo | neutro | negativo |
|---|---|---|---|
| **positivo** | 10 | 4 | 5 |
| **neutro** | 2 | 37 | 19 |
| **negativo** | 1 | 0 | 22 |

**Veredito:** qualidade adequada.

### Divergências

| id | título | referência | modelo |
|---|---|---|---|
| 1 | Novo Nordisk pagará até US$ 2,6 bi à empresa chinesa por pílula para perda de peso | neutro | negativo |
| 5 | Começa hoje período em que eleitores não podem ser presos; veja exceções | neutro | negativo |
| 15 | Proibição das bets: Qual o impacto no setor imobiliário e nos FIIs, segundo CEO da SiiLA | neutro | negativo |
| 18 | Vagas de emprego em aberto nos EUA caem em agosto; demissões permanecem baixas | neutro | negativo |
| 20 | Motiva, EcoRodovias e Eletromidia criam empresa de mídia para publicidade em rodovias | positivo | neutro |
| 44 | Bitcoin sobe depois de recuar até os US$ 82 mil e continua atraindo fluxo comprador | positivo | negativo |
| 45 | Quanto é a multa por não votar? Saiba o que fazer caso não consiga justificar | neutro | negativo |
| 74 | STF: Gilmar sugere ampliar controle sobre precatórios e fala em apuração de magistrados e advogados por supostas irregularidades | neutro | negativo |
| 77 | Nova pesquisa Datafolha para presidente mede impacto de escândalos antes do primeiro turno | neutro | negativo |
| 79 | Vemos leve melhora na trajetória do déficit por causa da saída do efeito dos precatórios, diz secretário do Tesouro | positivo | negativo |
| 84 | Redução do desemprego em agosto foi puxado por aumento de ocupado, mostra IBGE | positivo | negativo |
| 85 | Bolsas de NY rondam a estabilidade antes de dados de mercado de trabalho | neutro | negativo |
| 90 | Análise: O Iraque que Washington deixa para trás | neutro | negativo |
| 102 | Atlas Critical Minerals estima 24 milhões de toneladas de minério de grafite em projeto em MG | positivo | neutro |
| 108 | Dólar recua e real se alinha a pares emergentes após estresse na véspera | positivo | negativo |
| 109 | Forças dos EUA deixam Iraque após duas décadas e abrem espaço para o Irã | neutro | negativo |
| 110 | Juros futuros recuam com alívio externo | positivo | negativo |
| 114 | Desemprego fica em 5,3% no trimestre até agosto, mostra IBGE | neutro | negativo |
| 128 | Pearson adquire plataforma de inteligência de habilidades em IA Workera | neutro | positivo |
| 130 | IGP-M sobe 1,57% em setembro acumula alta de 3,34% em 12 meses | negativo | positivo |
| 131 | Manhã no mercado: Petróleo e juros americanos recuam, mas guerra no Irã e eleição mantêm investidores em alerta | neutro | negativo |
| 133 | PF apreende R$ 220 mil em operação contra atuação de facção nas eleições | neutro | negativo |
| 136 | OCDE: Brasil amplia número de professores nos primeiros anos do fundamental | neutro | positivo |
| 138 | Gasto por aluno no Brasil é 70% menor que a média da OCDE, mostra relatório | neutro | negativo |
| 141 | Capacitismo atinge 76% das pessoas com deficiência no mercado de trabalho | neutro | negativo |
| 149 | Diretor da ANP diz ter recebido reclamações ‘jocosas’ de executivos da Petrobras sobre ‘gas release’ | neutro | negativo |
| 151 | Ministro do Comércio de Cuba nega conversas com pessoas ligadas a Trump | neutro | negativo |
| 157 | E se os EUA barrarem exportações de diesel, quais impactos para a Bolsa brasileira? | neutro | negativo |
| 158 | Motiva, EcoRodovias e Eletromidia criam empresa de mídia para publicidade em rodovias | positivo | neutro |
| 173 | Lenda do tênis pede boicote aos Grand Slams por causa de premiação | neutro | negativo |
| 189 | Serena Assist lança plano Unique para até 12 pessoas | positivo | neutro |
