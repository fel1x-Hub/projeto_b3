# Deploy na nuvem (grátis, sem cartão)

Este arquivo **não guarda segredos**: só endereços e onde cada credencial está.

## Em produção (desde 02/10/2026)

| O quê | Onde |
|---|---|
| Site | https://projeto-b3-theta.vercel.app (Vercel, projeto `projeto-b3`) |
| API | https://projeto-b3-api.onrender.com (Render, serviço `projeto-b3-api`) · saúde: `/health` |
| Banco das telas | Neon, projeto `projeto-b3` (aws-us-east-1, Postgres 18) |
| Pipeline | GitHub Actions: *Ciclo intradiário*, *Pipeline diário* e *Inicializar nuvem* |
| Banco de trabalho | cache do Actions (`banco-v1-*`); pacote inicial e backup semanal no Release `dados` |
| App desktop | Release `desktop-v1.0` → `ProjetoB3.exe` |

## Como funciona

| Peça | Serviço (grátis) | O que faz |
|---|---|---|
| Pipeline | **GitHub Actions** (sem custo porque o repositório é público) | Ciclo a cada 15 min no pregão e pipeline completo às 21h30. O banco de trabalho (SQLite) fica guardado no cache do Actions entre as execuções. |
| Banco das telas | **Neon** (Postgres, 0,5 GB) | Guarda só o que as telas leem (~200 MB), a sua carteira e os relatórios. |
| API | **Render** (web service grátis) | FastAPI lendo do Neon. Dorme após 15 min sem uso e leva ~1 min para acordar. |
| Site | **Vercel** | React. Cada push na `main` publica sozinho. |
| App desktop | **GitHub Releases** | O `ProjetoB3.exe`, gerado pelo Actions. |

A carteira (operações e posições da XP) vive **só no Neon**, nunca no repositório nem no pacote do banco.

## Passo a passo (uma vez só)

### 1. Neon (banco)
1. Entre em neon.tech com o GitHub. Crie um projeto `projeto-b3`, com Postgres 17 e região AWS US East (N. Virginia).
2. Em **Connect**, copie a *connection string* (`postgresql://...`). Ela é a `DATABASE_URL`.
   - Feito em 02/10/2026 (projeto `projeto-b3`).

### 2. Segredos do GitHub (para o pipeline)
No repositório: **Settings → Secrets and variables → Actions → New repository secret**. Cadastre:

| Nome | Valor |
|---|---|
| `DATABASE_URL` | a string do Neon |
| `GEMINI_API_KEY` | a mesma chave do seu `.env` |
| `PLUGGY_CLIENT_ID`, `PLUGGY_CLIENT_SECRET`, `PLUGGY_ITEM_IDS` | opcionais (XP via Meu Pluggy) |

### 3. Banco inicial
1. No seu PC: `python scripts/empacotar_banco.py`. Isso gera `data/banco.tar.gz` (~420 MB, **sem** a carteira).
2. No GitHub, abra **Releases → Draft a new release**. Em *Choose a tag*, digite `dados` e crie a tag. O título é `Dados`. Anexe o `data/banco.tar.gz` e clique em **Publish release**.
3. Em **Actions → Inicializar nuvem → Run workflow**, rode o workflow. Leva uns 15 minutos. Ao final, o Neon está preenchido e o banco está no cache do Actions.

### 4. Render (API)
1. Entre em render.com com o GitHub. Vá em **New → Blueprint**, escolha o repositório `projeto_b3` e confirme. O arquivo `render.yaml` já descreve o serviço.
2. Preencha o que ele pedir:
   - `DATABASE_URL` e `GEMINI_API_KEY`;
   - `API_ORIGENS` (deixe `https://exemplo.vercel.app` por enquanto; o passo 5 troca);
   - os `PLUGGY_*`, que são opcionais.
3. Depois do deploy, anote:
   - **URL da API:** https://projeto-b3-api.onrender.com
   - **API_TOKEN**: gerado pelo Render e diferente do de desenvolvimento. Fica em serviço → Environment, e uma cópia em `API_TOKEN_PRODUCAO` no `.env` local.
4. Teste abrindo `<URL>/health` no navegador. Deve responder `{"ok": true}`, podendo levar ~1 min na primeira vez.

### 5. Vercel (site)
1. Entre em vercel.com com o GitHub. Vá em **Add New → Project** e importe `projeto_b3`.
2. Em **Root Directory**, coloque `frontend`. A Vercel detecta o Vite sozinha.
3. Em **Environment Variables**, crie `VITE_API_URL` com a URL da API (passo 4). Faça o deploy.
4. **URL do site:** https://projeto-b3-theta.vercel.app
5. O CORS já aceita os endereços `projeto-b3*.vercel.app` (`API_ORIGENS_REGEX` no `render.yaml`). Não precisa mexer no Render.
6. Abra o site e cole o `API_TOKEN` do Render.

### 6. App desktop
1. Baixe o `ProjetoB3.exe` em **Releases → App desktop**. Não precisa instalar nem ter administrador.
2. Na primeira vez, informe o endereço da API e o token (menu **Conexão…**). Eles ficam guardados no seu usuário do Windows.

### 7. Desligar o agendador do PC
Com a nuvem funcionando, o agendador local vira redundante. Para removê-lo:
`powershell -ExecutionPolicy Bypass -File scripts\instalar_agendador.ps1 -Remover`

## Operação

### Onde está cada credencial

| Credencial | Onde fica |
|---|---|
| `DATABASE_URL` | Neon (origem), segredos do GitHub e Render → Environment |
| `GEMINI_API_KEY` | Google AI Studio (origem), `.env` local, segredos do GitHub e Render |
| `API_TOKEN` de produção | Render → Environment; o site guarda no navegador e o app nas configurações do usuário |
| `API_TOKEN` de desenvolvimento | `.env` local |
| `PLUGGY_*` | dashboard.pluggy.ai (origem), segredos do GitHub e Render |

### Rodar à mão quando um agendamento falhar
**Actions →** *Pipeline diário* ou *Ciclo intradiário* **→ Run workflow**. O intradiário tem a opção "forçar", que roda fora do pregão.

O agendamento do GitHub pode atrasar alguns minutos. O workflow diário reativa os agendamentos sozinho, para o GitHub não desligá-los depois de 60 dias sem commits.

### Logs
- **Pipeline:** Actions → a execução → cada passo. O passo "Log" mostra o fim do `logs/app.log`.
- **API:** Render → serviço → Logs. Não são logados valores da carteira.
- **Banco:** Neon → Monitoring (uso de espaço e de computação).

### Desfazer (rollback)
- **API:** Render → Deploys → um deploy anterior → *Rollback*.
- **Site:** Vercel → Deployments → um anterior → *Promote to Production*.
- **Banco de trabalho:** toda sexta à noite o Actions grava `banco-backup.tar.gz` no Release `dados`. Para voltar a ele, rode *Inicializar nuvem* com o arquivo `banco-backup.tar.gz`.
- **Código:** `git revert` do commit e push. Render e Vercel publicam de novo sozinhos.

### Limites grátis a vigiar
- **Neon:** 0,5 GB e 100 CU-horas por mês. Veja em Monitoring; hoje o uso é de ~200 MB.
- **Render:** 750 horas por mês. O serviço dorme quando ninguém usa, e por isso a conta fecha.
- **Actions cache:** 10 GB por repositório. As cópias antigas do banco são descartadas sozinhas e só a mais recente importa.
