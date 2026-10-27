# 🤖 SEI-Agent

> Coleta processos do SEI-RJ, entrega ao Power Automate/AI Builder para análise automática e confere o resultado, com envio opcional pelo Teams e controle em banco local.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Selenium](https://img.shields.io/badge/Selenium-WebDriver-green?logo=selenium)](https://www.selenium.dev/)
[![SQLite](https://img.shields.io/badge/Database-SQLite-lightgrey?logo=sqlite)](https://www.sqlite.org/)
[![Power Automate](https://img.shields.io/badge/Power%20Automate-AI%20Builder-informational)](https://powerautomate.microsoft.com/)

---

## 📋 Sumário

- [Sobre o Projeto](#-sobre-o-projeto)
- [Funcionalidades](#-funcionalidades)
- [Arquitetura](#-arquitetura)
- [Pré-requisitos](#-pré-requisitos)
- [Instalação](#-instalação)
- [Estrutura de Arquivos](#-estrutura-de-arquivos)
- [Senha do SEI](#-senha-do-sei)
- [Configuração (.env)](#-configuração-env)
- [Como Usar](#-como-usar)
- [Power Automate e SharePoint](#-power-automate-e-sharepoint)
- [Leitura e Validação das Análises](#-leitura-e-validação-das-análises)
- [Envio pelo Teams](#-envio-pelo-teams)
- [Banco de Dados](#-banco-de-dados)
- [Códigos de Saída](#-códigos-de-saída)
- [Execução Agendada](#-execução-agendada)
- [Testes](#-testes)
- [Contribuição](#-contribuição)

---

## 📌 Sobre o Projeto

O **SEI-Agent** coleta processos do SEI-RJ com a biblioteca `jupiter-subtes`, transforma cada um num JSON de entrada e o entrega ao **Power Automate/AI Builder**, que gera uma análise em Markdown. Quando a análise volta, o agente a corrige no formato, confere contra o JSON de entrada e, se configurado, a envia a uma pessoa pelo Teams.

O Python **não chama a IA** e **não altera o processo no SEI**. A IA fica no Power Automate, e a análise é uma proposta sujeita à revisão humana.

O JSON traz um bloco `pre_calculado`, calculado por regra fixa (`automate/exportador.py` e `automate/extracao.py`), que o `prompt.md` manda a IA usar sem recalcular:

- data de referência, despacho demandante (com a data de assinatura, que é a chegada à nossa unidade), solicitante da demanda (já em frase pronta) e nível da demanda;
- solicitante origem (a unidade, quando o documento de ordem 1 é interno);
- situação de resposta (a parte objetiva) e competência (quando decorre do endereçamento);
- linha do tempo completa, com destinatário (linhas "À / Ao / Com vistas à"), data de assinatura e o papel dos documentos que têm regra (a IA a usa só para consulta; ela não entra na resposta);
- prazos encontrados nos textos, já comparados com a data de referência e com a chegada (situação, dias e documentos que os citam);
- alertas objetivos (despacho demandante sem endereçamento expresso, documentos sem texto, planilhas não lidas).

Todo o conteúdo enviado à IA usa o nome atual das unidades que mudaram de nome: **SUPCONC → SUPCONFI**, **SUPGO → SUPHOB** e **SUPAEF → SUPADFIN**. E-mails como `supconc.subtes@...` e nomes de documentos ficam como na fonte. Planilhas Excel da árvore não são clicadas (o navegador as baixaria); entram na lista como `[SEM TEXTO EXTRAÍDO: planilha Excel não lida]`.

---

## ✨ Funcionalidades

### 1. Coleta no SEI
- Login com usuário do `.env` e senha guardada no **Gerenciador de Credenciais do Windows**
- Dois modos de seleção: processos com um **marcador** (`marcador`) ou processos **novos** no Controle de Processos (`novos`)
- Leitura do texto dos documentos pelo HTML do SEI e, quando o texto é curto, pelo anexo (PDF e Word)
- A pasta de anexos de cada processo é apagada assim que o JSON é gerado

### 2. Entrega e análise
- Geração de `automate/entrada/ENTRADA_*.json` com o bloco `pre_calculado`
- Cópia do JSON para a pasta do SharePoint sincronizada pelo OneDrive, o que dispara o fluxo do Power Automate (sem API nem webhook)
- Espera pela análise na pasta de saída, com tempo máximo configurável, e **fecha o navegador** durante a espera
- Se a entrega falhar, o JSON já gerado é reaproveitado na próxima execução, **sem coletar o processo de novo**

### 3. Correção e validação
- Correção automática de **formato** e de **nomes antigos de unidades**
- Validação do conteúdo contra o JSON de entrada, com relatório `.validacao.txt` de `ERRO` e `AVISO` para revisão humana

### 4. Teams
- Envio da análise corrigida como texto, por webhook, com até 3 tentativas nas falhas passageiras
- A chave do webhook (`sig=`) nunca vai para o log

### 5. Controle e acompanhamento
- Banco SQLite com o estado de cada processo, as execuções e o histórico de erros de cada análise
- Relatório de linha de comando (`python -m banco.relatorio`)
- Teto de tentativas por processo e **código de saída** pronto para o Agendador de Tarefas

---

## 🧩 Arquitetura

```
┌───────────────────────────────────────────────────────────┐
│                         main.py                           │
│     (credenciais, seleção, coleta, entrega, espera)       │
└──────┬─────────────────────┬─────────────────────┬────────┘
       │                     │                     │
       ▼                     ▼                     ▼
┌──────────────┐   ┌──────────────────┐   ┌─────────────────┐
│ sei/         │   │ automate/        │   │ banco/          │
│ SEIService   │   │ exportador.py    │   │ controle.py     │
│ (jupiter)    │   │ extracao.py      │   │ relatorio.py    │
│ credenciais  │   │ saidas.py        │   │  agente.db      │
└──────┬───────┘   │ correcao.py      │   └─────────────────┘
       │           │ validador.py     │
       ▼           │ teams.py         │
┌──────────────┐   └────────┬─────────┘
│ extratores/  │            │
│ PDF / Word   │            │
└──────────────┘            │
                            ▼
        ┌──────────────────────────────────────┐
        │   OneDrive  →  SharePoint  →  Power  │
        │   (entrada)                Automate  │
        │   (saida)   ←  análise .md ←  (IA)   │
        └──────────────────────────────────────┘
```

**Fluxo de dados:**

```
SEI → jupiter → ProcessoSEI → automate/entrada/ENTRADA_*.json
                                      │
              cópia para a pasta do SharePoint sincronizada (OneDrive)
                                      │
        Power Automate ("Quando um arquivo é criado") → Run a prompt → análise .md
                                      │
              pasta de saída sincronizada (somente leitura)
                                      │
          correção de formato → validação → automate/saida/*.md + .validacao.txt
                                      │
                         Teams (opcional) + banco de dados
```

---

## 📋 Pré-requisitos

- **Python** 3.10 ou superior (os testes rodam no 3.14)
- **Windows**, por causa do Gerenciador de Credenciais e do OneDrive sincronizado
- Navegador e driver compatíveis com a `jupiter-subtes`
- Acesso ao **SEI-RJ** com usuário, órgão e unidade configurados
- **OneDrive** sincronizando as pastas `entrada` e `saida` do SharePoint (para a parte do Power Automate)
- Webhook do Teams, se quiser receber as análises

---

## 🚀 Instalação

```powershell
cd "Z:\Programas da SUPCONC\SEI-Agent"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

| Pacote | Uso |
|---|---|
| `jupiter-subtes` | Biblioteca interna de automação do SEI (fica com `>=`; atualize com `pip install --upgrade jupiter-subtes`) |
| `python-dotenv` | Leitura do `.env` |
| `pdfplumber` / `python-docx` | Texto de anexos PDF e Word |
| `requests` | Envio ao webhook do Teams |
| `keyring` | Senha do SEI no Gerenciador de Credenciais do Windows |

As versões do `requirements.txt` estão fixadas, exceto a `jupiter-subtes`. Para desenvolver e rodar os testes, instale `requirements-dev.txt` no lugar: ele inclui o `requirements.txt` e acrescenta o `pytest`.

---

## 📁 Estrutura de Arquivos

```
SEI-Agent/
│
├── main.py                  # Ponto de entrada: coleta, entrega e espera pelas análises
├── config.py                # Lê o .env e define pastas e padrões
├── prompt.md                # Cópia de referência do prompt da análise (Power Automate)
├── prompt_revisor.md        # Prompt de revisão de uma análise contra um checklist
├── .env.example             # Modelo do .env (o .env real não é versionado)
├── requirements.txt         # Dependências de execução
├── requirements-dev.txt     # Dependências de execução + pytest
│
├── sei/
│   ├── sei_service.py        # SEIService: login, seleção e coleta dos processos
│   ├── modelos.py            # ProcessoSEI, DocumentoSEI
│   └── credenciais.py        # Senha do SEI no Gerenciador de Credenciais
│
├── extratores/
│   └── extrator.py           # Texto de anexos PDF e Word (Excel não é lido)
│
├── automate/
│   ├── exportador.py         # JSON de entrada e cópia para o SharePoint
│   ├── extracao.py           # Regras que alimentam o bloco pre_calculado
│   ├── saidas.py             # Lê as análises novas, corrige, valida e registra
│   ├── correcao.py           # Correções de formato e de nomes de unidades
│   ├── validador.py          # Confere a análise contra o JSON de entrada
│   ├── teams.py              # Envio da análise pelo Teams
│   ├── entrada/              # ENTRADA_*.json (gerada)
│   ├── saida/                # Análises corrigidas e .validacao.txt (gerada)
│   └── erros/                # Reservada; o agente só cria a pasta
│
├── banco/
│   ├── controle.py           # SQLite: processos, execuções e histórico
│   ├── relatorio.py          # Consulta pela linha de comando
│   └── agente.db             # Banco (gerado; não versionado)
│
├── tests/                    # Testes (pytest)
├── downloads/                # Anexos durante a coleta (gerada)
└── logs/
    ├── execução/             # Logs das execuções reais (e erros/ só com nível ERROR)
    └── tests/                # Logs das rodadas de pytest
```

> `downloads/` só guarda, depois da coleta, o que pertence a processos que **falharam** (anexos e diagnóstico da árvore, com HTML e print de tela), para investigação. Apague-os depois.

---

## 🔑 Senha do SEI

A senha fica no **Gerenciador de Credenciais do Windows** (biblioteca `keyring`), criptografada e ligada ao usuário do Windows que a cadastrou. Ela **nunca** vai para o `.env`, o banco nem os logs. Cadastre uma vez, com `SEI_USUARIO` preenchido no `.env`:

```powershell
python -m sei.credenciais --cadastrar   # pede a senha duas vezes e guarda; também serve para trocá-la
python -m sei.credenciais --verificar   # diz se há senha guardada, sem mostrá-la
python -m sei.credenciais --apagar
```

Na execução, o agente usa a senha guardada. Sem ela, **só pergunta se houver alguém no terminal**; em execução agendada, sem terminal, ele termina com código `1` e o log diz como cadastrar. Quando a senha do SEI mudar, rode `--cadastrar` de novo.

> A senha é ligada ao usuário do Windows: o Agendador de Tarefas precisa rodar **com o mesmo usuário** que a cadastrou, e não funciona como `SYSTEM`.

---

## 🔧 Configuração (.env)

Edite o `.env` (copiado de `.env.example`; ele está no `.gitignore`, não o versione nem o compartilhe). Variável ausente ou vazia = valor padrão. Valor que ainda é o texto-modelo do `.env.example` (começa com `<`, como `<seu usuário do SEI>`) conta como não preenchido, e o agente avisa no log quais variáveis estão assim. Número ou `True/False` inválido faz o programa parar na partida, dizendo qual variável está errada.

| Variável | Padrão | Para que serve |
|---|---|---|
| `SEI_USUARIO` | (pergunta ao executar, se houver alguém no terminal) | Usuário do SEI; também é a chave da senha guardada no Windows |
| `SEI_ORGAO` | `SEFAZ` | Órgão no login |
| `SEI_UNIDADE` | `SUPCONFI` | Unidade em que o agente trabalha |
| `SEI_MODO` | `novos` | `marcador` (processos com o marcador abaixo) ou `novos` (processos que surgirem no Controle de Processos depois da primeira execução) |
| `SEI_MARCADOR` | `AGENTE - ANALISAR` | Marcador dos processos a analisar, no modo `marcador` |
| `LIMITE_TEXTO_DOCUMENTO` | `80` | Documento do SEI com menos caracteres que isso é baixado e lido pelo anexo |
| `HEADLESS` | `False` | `True` roda o navegador sem janela |
| `TENTATIVAS_MAXIMAS` | `3` | Quantas vezes seguidas um processo pode falhar (coleta ou entrega) antes de o agente parar de tentá-lo sozinho |
| `SHAREPOINT_PASTA_ENTRADA` | (vazio = não copia) | Pasta `entrada` sincronizada pelo OneDrive |
| `SHAREPOINT_PASTA_SAIDA` | (vazio = não lê) | Pasta `saida` sincronizada pelo OneDrive |
| `SAIDA_ESPERA_MINUTOS` | `5` | Quanto esperar, no total, pelas análises do Power Automate |
| `SAIDA_INTERVALO_SEGUNDOS` | `20` | De quanto em quanto tempo olhar a pasta de saída |
| `TEAMS_WEBHOOK_URL` | (vazio = não envia) | Webhook do Teams |
| `TEAMS_DESTINATARIOS` | (vazio = não envia) | E-mails de quem recebe a análise, separados por vírgula |
| `TEAMS_LIMITE_CARACTERES` | `25000` | O Teams recusa mensagens maiores; o texto é cortado |

---

## 🎯 Como Usar

### Passo 1 — Cadastrar a senha
Preencha `SEI_USUARIO` no `.env` e rode `python -m sei.credenciais --cadastrar` (veja [Senha do SEI](#-senha-do-sei)).

### Passo 2 — Testar com um processo
```powershell
python main.py --processo "SEI-040009/001813/2026"
```
O agente trabalha só nesse processo e ignora o modo, o marcador e o banco. Sempre coleta de novo.

### Passo 3 — Executar normalmente
```powershell
python main.py
```
Seleciona os processos conforme `SEI_MODO`, coleta, gera e entrega o JSON de cada um e espera as análises. No modo `novos`, a **primeira** execução só registra o que já existe no Controle de Processos (status `baseline`) e não exporta nada.

| Opção | O que faz |
|---|---|
| `--processo "SEI-..."` | Trabalha só nesse processo; ignora o modo, o marcador e o banco |
| `--reanalisar` | Não descarta os processos que o banco já conhece. No modo `novos` isso pega **todo** o Controle de Processos: use com cuidado |
| `--sem-saida` | Não espera as análises (as copia depois com `python -m automate.saidas`) |

### Passo 4 — Esperar as análises
Com `SHAREPOINT_PASTA_SAIDA` configurada, depois de entregar os JSONs o agente **fecha o navegador** e aguarda as análises aparecerem na pasta de saída, até `SAIDA_ESPERA_MINUTOS`, olhando a cada `SAIDA_INTERVALO_SEGUNDOS`.

- Só entram as análises **novas dos processos desta execução**: o que já estava na pasta antes de começar (mesmo do mesmo processo) e as análises de outros processos são ignorados, sem serem corrigidos, validados nem enviados.
- Se o processo já tem análise na pasta, o agente espera a versão nova dele (nova = conteúdo diferente).
- Cada análise que chega é corrigida e validada na hora, e o resultado vai para `automate/saida`.
- As que não chegarem a tempo viram um aviso no log, e `python -m automate.saidas` pega depois.
- `Ctrl+C` encerra só a espera.

### Passo 5 — Acompanhar
```powershell
python -m banco.relatorio                                       # status, pendentes, desistências, últimas análises e execuções
python -m banco.relatorio --processo "SEI-040009/001847/2026"   # as análises de um processo, com os erros de cada uma
python -m banco.relatorio --horas 4 --execucoes 20 --analises 30
```
Os logs ficam em `logs/execução`.

### Comandos avulsos

| Comando | Para que serve |
|---|---|
| `python -m automate.saidas` | Corrige e valida as análises novas da pasta de saída (e as envia ao Teams) |
| `python -m automate.saidas --refazer` | Refaz todas; não envia ao Teams |
| `python -m automate.saidas --arquivo ANALISE_X.md` | Só esse arquivo; também serve para reenviar ao Teams |
| `python -m automate.saidas --sem-teams` | Não envia ao Teams |
| `python -m automate.validador A.md E.json` | Confere uma análise contra o JSON de entrada |
| `python -m automate.teams --teste` | Manda uma mensagem de teste aos destinatários |
| `python -m sei.credenciais --cadastrar` | Guarda ou troca a senha do SEI |

---

## 📨 Power Automate e SharePoint

A pasta `5 - Automação/05 - Agente/entrada` do site SUBTES está sincronizada no OneDrive. Preencha `SHAREPOINT_PASTA_ENTRADA` com o caminho local dela (ex.: `C:\Users\<usuario>\OneDrive - SEFAZ-RJ\SUBTES - SUPCONC\5 - Automação\05 - Agente\entrada`). Depois de gerar `automate/entrada/ENTRADA_*.json`, o agente copia o arquivo para essa pasta; o cliente do OneDrive faz o upload e o fluxo é disparado pelo arquivo novo. Variável vazia = não copia.

Se a pasta não existir (OneDrive fechado ou não sincronizado) ou a cópia falhar, o processo fica com status `erro_envio` e é reenviado na próxima execução **sem ser coletado de novo**: o JSON já gerado é reaproveitado, se o arquivo ainda existir.

A pasta `saida` (`5 - Automação/05 - Agente/saida`) também é sincronizada, e `SHAREPOINT_PASTA_SAIDA` aponta para ela. Ela **só é lida**: nada é gravado nela, para não disparar o fluxo. O fluxo em si é configurado no Power Automate, fora deste projeto. Os prompts estão na raiz: `prompt.md` (a análise do processo) e `prompt_revisor.md` (a revisão de uma análise contra um checklist).

---

## ✅ Leitura e Validação das Análises

Para cada `.md` o agente acha o JSON de entrada pelo número da seção "Processo" (o nome do arquivo não precisa trazê-lo), corrige o que é só **formato** ou **nome de unidade** e confere o resto com o `validador`.

**Correções automáticas:**

- a marcação `<documents>` ... `</documents>`, que a IA às vezes põe em volta da análise, é removida (no Teams ela fazia o `## Processo` aparecer como texto cru);
- `## Roteiro` e `## Despacho` viram `###` dentro de Proposta;
- linhas "Preencher:" sem nenhum `[PREENCHER]` na análise saem dos Alertas;
- alertas ganham `- ` e uma linha em branco entre eles;
- despacho: linha em branco após o vocativo e entre parágrafos, e frase partida em dois parágrafos volta a ser uma só;
- nomes antigos de unidades (SUPCONC, SUPGO, SUPAEF) são trocados pelos atuais, fora de e-mails e de nomes de documentos.

**Validação.** A análise tem 9 seções (`##`): Processo, Solicitante Origem, Solicitante Demanda, Contexto, Demanda, Pendências, Informações Relevantes, Proposta (`### Roteiro` e `### Despacho`) e Alertas. Cada `ERRO` é a análise contrariando o que o sistema calculou ou o formato (seções fora do formato, nomes antigos de unidades, campos técnicos, Solicitante Demanda com o nível, situação, prazo, competência, tipo e roteiro da proposta, alertas copiados e linhas "Preencher:"). `AVISO` pede só uma olhada.

**Resultado** em `automate/saida`: `<nome>.md` corrigido e `<nome>.validacao.txt` com as correções feitas e os `ERRO`/`AVISO` que restam. Erros de conteúdo (e-mail trocado, prazo, situação, seção ausente) **não são corrigidos**: aparecem no relatório para revisão humana.

---

## 💬 Envio pelo Teams

Cada análise corrigida pode ser enviada a uma pessoa pelo Teams, por um **webhook** (o JSON enviado tem o formato de `GraphAPI.enviar_mensagem` da jupiter: `{"destinatarios": [...], "mensagem": "..."}`). Sem webhook ou sem destinatário, nada é enviado.

- O webhook não aceita anexo, então a análise vai **como texto**: um cabeçalho mínimo (`SEI-Agent` em texto simples e uma linha `---`, necessários para o Teams formatar o `## Processo` como título; `#` ou negrito no cabeçalho desfazem a formatação) e, em seguida, o `.md` corrigido, sem lista de problemas nem caminho de arquivo.
- Textos acima de `TEAMS_LIMITE_CARACTERES` são cortados, e o corte fica no log; o arquivo completo continua em `automate/saida`.
- Os erros e avisos da validação não vão na mensagem: ficam em `<nome>.validacao.txt`.
- No `main.py`, só vai ao Teams a análise **nova** dos processos daquela execução. Já `python -m automate.saidas` envia toda análise nova que encontrar; `--refazer` e `--sem-teams` não enviam.
- **Tentativas:** falha de rede, de certificado SSL, do servidor (5xx) ou limite de uso (429) é tentada até 3 vezes (pausas de 5 e 15 s). Erro 4xx não é repetido.
- Se nenhuma tentativa funcionar, o erro vai para o log e **nunca interrompe a coleta**; o banco guarda `teams_enviado = 0`, e `python -m automate.saidas --arquivo X.md` reenvia.
- A URL do webhook contém uma assinatura (`sig=`) que funciona como senha: ela fica só no `.env` e é ocultada nos logs.

---

## 💾 Banco de Dados

O banco `banco/agente.db` tem três tabelas, criadas e atualizadas sozinhas (um banco antigo é migrado na primeira execução, sem perder as linhas):

### Tabela `processos` — o estado atual

É ela que decide o que o agente pega na próxima execução.

| Coluna | Tipo | Descrição |
|---|---|---|
| `numero` | TEXT | Número do processo no SEI (chave) |
| `status` | TEXT | Situação atual (veja a tabela abaixo) |
| `arquivo_entrada` / `arquivo_saida` | TEXT | Caminhos do JSON de entrada e da análise corrigida |
| `erro` | TEXT | Última mensagem de erro (ou o resumo da validação, se houve `ERRO`) |
| `atualizado_em` / `exportado_em` / `analisado_em` | TEXT | Datas e horas dos marcos |
| `falhas_seguidas` | INTEGER | Erros desde o último sucesso |
| `teams_enviado` | INTEGER | `1` enviado, `0` falhou, vazio = não tentado |
| `validacao_erros` / `validacao_avisos` | INTEGER | Contagens da última validação |

| Status | Significa | O agente pega de novo? |
|---|---|---|
| `baseline` | Já existia na primeira execução do modo `novos` | Não |
| `exportado` | JSON gerado e entregue (ou só local, se `SHAREPOINT_PASTA_ENTRADA` estiver vazia) | Não |
| `analisado` | A análise chegou e foi corrigida e validada (mesmo com `ERRO`: o resumo vai em `erro`) | Não |
| `erro_coleta` | A coleta no SEI falhou | Sim, até `TENTATIVAS_MAXIMAS` falhas seguidas |
| `erro_envio` | O JSON foi gerado, mas a cópia para o SharePoint falhou | Sim, reaproveitando o JSON, até o mesmo teto |

Ao chegar a `TENTATIVAS_MAXIMAS`, o agente deixa o processo de lado e registra o aviso no log; para tentar de novo, use `--processo`. Um novo `exportado` começa um ciclo novo: os dados da análise anterior saem da linha, mas o resultado de cada análise continua no `historico`.

### Tabela `execucoes` — uma linha por execução

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER | Número da execução |
| `inicio` / `fim` | TEXT | Começo e fim. **Sem `fim`, o programa caiu ou foi interrompido** |
| `modo` / `argumentos` | TEXT | `marcador`, `novos`, `processo` ou `saidas`, e as opções usadas |
| `selecionados` / `exportados` / `falhas` / `analises` | INTEGER | Totais (cada processo conta uma vez) |
| `codigo_saida` | INTEGER | Código de saída da execução |

### Tabela `historico` — uma linha por erro ou aviso

| Coluna | Tipo | Descrição |
|---|---|---|
| `analise` | INTEGER | Agrupa as linhas de uma mesma análise |
| `execucao_id` / `numero` / `arquivo` / `em` | — | Execução, processo, arquivo da análise e data |
| `tipo` | TEXT | `erro`, `aviso` ou `ok` (análise sem nenhum problema: uma única linha `ok`) |
| `mensagem` | TEXT | O texto do erro ou aviso |

Só é acrescentada, nunca sobrescrita. Falhas de coleta e de entrega **não** entram aqui: ficam em `processos` e na contagem de falhas da execução.

---

## 🔢 Códigos de Saída

**`python main.py`**

| Código | Significado |
|---|---|
| `0` | Todos os processos foram coletados e entregues (ou não havia nenhum) |
| `1` | A autenticação falhou, ou faltou usuário/senha sem ninguém no terminal, ou algum processo teve falha de coleta ou de entrega nesta execução |

Um processo de que o agente já desistiu (teto de tentativas) e uma análise com `ERRO` de validação **não** alteram o código: o primeiro aparece no `banco.relatorio`, e a segunda é entregue ao Teams e fica no `.validacao.txt`.

**Outros comandos**

| Comando | Código |
|---|---|
| `python -m automate.saidas` | `1` se alguma análise tiver `ERRO` de validação; `0` caso contrário |
| `python -m automate.teams --teste` | `0` enviou; `1` falhou; `2` sem webhook ou destinatário |
| `python -m sei.credenciais` | `0` ok; `1` falhou (senha não guardada, repetição diferente...); `2` uso incorreto ou sem usuário |
| `python -m banco.relatorio` | `0` ok; `2` banco não encontrado |

---

## ⏰ Execução Agendada

O agente roda sem ninguém na frente do computador quando a senha já está no Gerenciador de Credenciais. Cadastre a tarefa no PowerShell, com o seu usuário (ajuste o horário e o intervalo):

```powershell
$pasta = "\\cifs-zone1\tesouro\Programas da SUPCONC\SEI-Agent"
$acao = New-ScheduledTaskAction `
  -Execute "C:\Users\<usuario>\AppData\Local\Programs\Python\Python314\python.exe" `
  -Argument "`"$pasta\main.py`"" -WorkingDirectory $pasta
$gatilho = New-ScheduledTaskTrigger -Once -At 08:00 `
  -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Hours 10)
$config = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable
$quem = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName "SEI-Agent" -Action $acao -Trigger $gatilho -Settings $config -Principal $quem
```

- Use o caminho **UNC** (`\\cifs-zone1\...`), não a letra `Z:`: a unidade mapeada não existe na sessão do agendador.
- `-LogonType Interactive`: a tarefa só roda com o usuário logado, pois a senha, o OneDrive e o navegador dependem da sessão dele.
- `-MultipleInstances IgnoreNew`: se uma execução ainda estiver rodando no horário seguinte, o agendador não abre outra. O agente não tem trava própria contra duas execuções ao mesmo tempo (por exemplo, o agendador e você rodando `main.py` à mão).
- O computador precisa estar ligado, com o OneDrive aberto e na VPN, se for o caso. Teste antes à mão (`HEADLESS=True` evita a janela do navegador).
- Para acompanhar: `(Get-ScheduledTaskInfo -TaskName "SEI-Agent").LastTaskResult` (`0` = ok, `1` = falha) e `python -m banco.relatorio`.

---

## 🧪 Testes

```powershell
pip install -r requirements-dev.txt
pytest -q
```

Os testes não usam o SEI, o Teams, o OneDrive nem o Gerenciador de Credenciais de verdade (`tests/conftest.py` os desliga e isola o banco). O log de cada rodada vai para `logs/tests`, e os testes nunca gravam em `logs/execução`.

`tests/test_prompt.py` confere que o `prompt.md` continua de acordo com o validador (as 9 seções na ordem, `### Roteiro` e `### Despacho`, e os tipos de providência, competências e situações de resposta). Se ele falhar, o prompt e o `automate/validador.py` se afastaram: atualize um dos dois. Ele só enxerga o `prompt.md` deste repositório, então mantenha-o como cópia fiel do prompt que está no Power Automate.

---

## 🤝 Contribuição

Dúvidas, sugestões e reportes de inconsistências devem ser encaminhados ao responsável pelo projeto. Em caso de mudança nas premissas operacionais (marcadores do SEI, nomes de unidades, formato das análises, estrutura das pastas do SharePoint), atualize o `prompt.md` no Power Automate, o `automate/validador.py` e este README em conjunto.

---

<div align="center">
  <sub>SEI-Agent &nbsp;|&nbsp; SUPCONFI — SEFAZ-RJ</sub>
</div>
