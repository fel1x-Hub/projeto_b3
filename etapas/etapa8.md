# Etapa 8 — Deploy (desktop .exe + web gratuito)

## Objetivo
Empacotar o sistema como aplicativo desktop (.exe para Windows) e publicá-lo na web usando serviços gratuitos, com banco de dados em nuvem. Antes de implementar qualquer coisa, apresentar as opções ao usuário e esperar escolha.

## Pré-requisito
Etapa 7 concluída e funcionando localmente.

---

## 8.1 Planejamento obrigatório antes de codar

**O Claude deve apresentar uma tabela comparativa das opções abaixo e esperar o usuário escolher antes de escrever qualquer código de deploy.**

### Opções de hospedagem do backend (FastAPI)
| Serviço | Plano gratuito | Limite | Frio (dorme)? | Observação |
|---------|---------------|--------|---------------|------------|
| Render | Sim | 750h/mês | Sim, após 15min | Mais fácil de configurar |
| Railway | Sim (trial $5) | $5 de crédito | Não | Crédito acaba; precisa cartão depois |
| Fly.io | Sim | 3 VMs pequenas | Não | Requer CLI; mais flexível |
| Koyeb | Sim | 1 instância | Não | Boa opção para sempre ligado |

### Opções de banco de dados PostgreSQL gratuito
| Serviço | Plano gratuito | Limite de armazenamento | Observação |
|---------|---------------|------------------------|------------|
| Neon | Sim | 512 MB | Serverless; excelente integração com Render |
| Supabase | Sim | 500 MB | Tem painel visual; fácil de usar |
| Railway (Postgres) | Sim (trial) | Junto com o crédito | Conveniente se já usar Railway |
| ElephantSQL | Sim (Tiny Turtle) | 20 MB | Muito pequeno; só para testes |

### Opções de hospedagem do frontend (React)
| Serviço | Plano gratuito | Observação |
|---------|---------------|------------|
| Vercel | Sim, generoso | Melhor opção para React; deploy automático do GitHub |
| Netlify | Sim | Similar ao Vercel |
| Render (estático) | Sim | Mesma plataforma do backend; simplifica |
| GitHub Pages | Sim | Só estático; requer build manual |

**Combinação recomendada para apresentar ao usuário:** Render (backend) + Neon (banco) + Vercel (frontend). É totalmente gratuita, não dorme com configuração correta e tem boa documentação. Mas apresentar todas as opções e deixar o usuário decidir.

---

## 8.2 Migração do banco SQLite → PostgreSQL
1. Script de migração que lê o SQLite local e escreve no PostgreSQL em nuvem.
2. Ajustar `src/db/` para suportar ambos os bancos via variável de ambiente (`DATABASE_URL`).
3. SQLite continua como opção local (desenvolvimento e desktop offline).
4. Testar migração com dados reais antes de qualquer deploy.

## 8.3 Deploy do backend
1. `Dockerfile` para o backend FastAPI (imagem leve, ex: `python:3.11-slim`).
2. Variáveis de ambiente de produção documentadas em `.env.example` com comentários explicando cada uma.
3. Script de coleta agendado: o serviço de hospedagem escolhido provavelmente não tem cron nativo; avaliar opções (Render Cron Jobs, GitHub Actions agendado, ou script que roda dentro do próprio servidor).
4. Health check endpoint (`GET /health`) para o serviço monitorar se o backend está vivo.
5. Instruções passo a passo para o usuário configurar as credenciais no painel do serviço escolhido.

## 8.4 Deploy do frontend (web)
1. Configurar variável de ambiente `VITE_API_URL` apontando para o backend em produção.
2. Build de produção do React (`npm run build`).
3. Deploy automático via integração com GitHub (push na branch main dispara deploy).
4. Configurar domínio personalizado se o usuário tiver (opcional).
5. HTTPS é obrigatório; todos os serviços listados fornecem gratuitamente.

## 8.5 Aplicativo desktop (.exe)
Usar **Electron** empacotando o mesmo frontend React. O app desktop se conecta à API local (quando o backend está rodando na máquina) ou à API em nuvem.

1. Configurar `frontend/electron/` com `main.js` mínimo (abre janela, carrega o React).
2. `electron-builder` para gerar o instalador `.exe` (Windows) e `.dmg` (Mac) e `.AppImage` (Linux).
3. Modo offline: quando a API em nuvem não está acessível, tentar conectar em `localhost`. Mostrar aviso claro se nenhuma API estiver disponível.
4. Auto-updater opcional (electron-updater): se implementar, documentar onde hospedar os updates (GitHub Releases é gratuito).
5. Script `npm run electron:build` que gera os instaladores na pasta `dist/`.

## 8.6 Segurança mínima para produção
- Token de autenticação da API diferente em produção (gerado aleatoriamente, nunca o mesmo do desenvolvimento).
- CORS configurado para aceitar apenas o domínio do frontend em produção.
- Rate limiting na API para evitar abuso.
- Nunca logar dados sensíveis (posições, valores investidos) nos logs do servidor.

## 8.7 Documentação de credenciais e acesso
Ao final desta etapa, o Claude deve gerar um arquivo `DEPLOY.md` (fora do git, ou com seções em branco para o usuário preencher) com:
- URLs de produção (backend, frontend, banco).
- Onde cada credencial está configurada (qual painel, qual variável de ambiente).
- Como fazer rollback se algo der errado.
- Como rodar a coleta manualmente se o agendamento falhar.
- Como acessar os logs de produção.

## Critério de pronto
- Backend respondendo na URL de produção (`GET /health` retorna 200).
- Frontend acessível via URL pública, conectado ao backend de produção.
- Instalador `.exe` gerado, instalado e funcionando em Windows.
- Migração do banco concluída: dados históricos disponíveis em produção.
- `DEPLOY.md` gerado com todas as credenciais documentadas (valores em branco para o usuário preencher no documento local).
- Coleta diária agendada e funcionando (verificar logs após 24h).
