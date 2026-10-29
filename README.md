# Tradutor Live — Angular + FastAPI

Aplicação experimental para transcrever áudio do dispositivo de saída do Windows e traduzir trechos do inglês para português brasileiro usando a API Gemini.

## Arquitetura

- **Frontend:** Angular standalone + TypeScript + SCSS.
- **Backend local:** Python + FastAPI + WebSocket.
- **Captura:** Windows WASAPI loopback via SoundCard.
- **IA:** Gemini Live para transcrição e Gemini Flash Lite para tradução.
- **Segredos:** chave Gemini exclusivamente no arquivo `backend/.env`, nunca no Angular.

> A captura WASAPI deve ocorrer no computador do usuário. Por isso, hospedar apenas o frontend não transforma a aplicação em um serviço de captura remoto. Para uma demonstração pública, use screenshots/vídeo ou crie um modo de demonstração separado; não exponha a chave no navegador.

## Pré-requisitos

- Windows 10/11 com dispositivo de saída de áudio padrão.
- Python 3.11 ou 3.12 recomendado para testar a compatibilidade das dependências de áudio.
- Node.js compatível com a versão do Angular instalada.
- Chave da Gemini API com acesso aos modelos configurados.

## Backend

No Git Bash, na raiz deste repositório:

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edite `backend/.env` localmente e insira sua chave. Não compartilhe nem faça commit desse arquivo.

Inicie o backend:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

A API deve responder em `http://127.0.0.1:8000/api/health` e a documentação fica em `http://127.0.0.1:8000/docs`.

## Frontend Angular

Abra um segundo terminal na raiz do repositório:

```bash
cd frontend
npm install
npm start
```

Acesse `http://localhost:4200`. O frontend conecta ao backend local por WebSocket em `ws://127.0.0.1:8000/ws/translation`.

## Segurança da chave

- Nunca coloque `GEMINI_API_KEY` em `environment.ts`, em componentes Angular, no HTML, em arquivos `.ts` ou em variáveis `VITE_`/`NG_APP_` compiladas no navegador.
- Não publique `.env`; publique apenas `.env.example` sem valores secretos.
- Se uma chave real já foi incluída em ZIP, commit ou repositório público, revogue-a e gere outra.
- No GitHub, confira também o histórico Git e os artefatos antigos; remover o arquivo do último commit não apaga necessariamente uma chave do histórico.
- Configure cotas e alertas de uso no provedor.

## Publicação para portfólio

1. Publique o código-fonte no GitHub sem `.env`, credenciais, caches ou `node_modules`.
2. Hospede uma página de apresentação/estudo de caso com arquitetura, screenshots, limitações e vídeo de demonstração.
3. Uma demo online que captura o áudio do computador não pode ser implementada apenas com um backend hospedado: a captura atual precisa acontecer localmente. Para uso público ao vivo, uma futura extensão Chrome pode capturar o áudio da aba com permissão do usuário, ou podemos criar um modo separado que receba arquivo de áudio.
4. Não publique uma chave compartilhada para que visitantes a utilizem. Se no futuro houver um backend público, ele precisará de autenticação, rate limiting, controle de custos e limites por usuário.

## Limitações conhecidas

- A captura de áudio Windows via SoundCard ainda precisa de teste prolongado; o projeto original apresentou `access violation` em alguns ambientes.
- A tradução é gerada por trechos finalizados e pode ter atraso em relação à transcrição parcial.
- A API Gemini tem cotas e limites; não é correto prometer uso ilimitado gratuito.
- Esta versão Angular é uma adaptação inicial da interface, não uma certificação de que o problema de captura foi resolvido.
