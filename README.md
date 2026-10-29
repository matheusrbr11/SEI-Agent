# 🤖 SEI-Agent

> Busca processos no SEI, manda para a análise automática e entrega o resultado já conferido.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Selenium](https://img.shields.io/badge/Selenium-WebDriver-green?logo=selenium)](https://www.selenium.dev/)
[![SQLite](https://img.shields.io/badge/Database-SQLite-lightgrey?logo=sqlite)](https://www.sqlite.org/)
[![Power Automate](https://img.shields.io/badge/Power%20Automate-AI%20Builder-informational)](https://powerautomate.microsoft.com/)

---

## 📋 Sumário

- [Sobre o Projeto](#-sobre-o-projeto)
- [Funcionalidades](#-funcionalidades)
- [Como Funciona](#-como-funciona)
- [Pré-requisitos](#-pré-requisitos)
- [Instalação](#-instalação)
- [Estrutura de Arquivos](#-estrutura-de-arquivos)
- [Configuração](#-configuração)
- [Como Usar](#-como-usar)
- [Execução Agendada](#-execução-agendada)
- [Testes](#-testes)
- [Contribuição](#-contribuição)
- [Autor](#-autor)

---

## 📌 Sobre o Projeto

O **SEI-Agent** é um programa que trabalha sozinho: entra no SEI, escolhe os processos que precisam de análise, lê os documentos de cada um e envia tudo para uma análise automática feita pelo AI Builder, dentro do Power Automate. Quando a análise fica pronta, o programa a revisa, corrige o que for só de formato e avisa quem precisa saber, pelo Teams.

Ele **não altera nada no SEI**. A análise é uma proposta e deve sempre ser revisada por uma pessoa.

---

## ✨ Funcionalidades

- **Coleta no SEI:** entra com o seu usuário, escolhe os processos (pelos que têm um marcador ou pelos que acabaram de chegar) e lê os documentos, inclusive os anexos em PDF e Word.
- **Envio para a análise:** entrega os dados de cada processo ao Power Automate, onde o AI Builder faz a análise, e espera ela voltar.
- **Revisão da análise:** corrige o formato e confere o conteúdo com os dados do processo. O que precisa de olho humano fica num relatório.
- **Aviso pelo Teams:** envia a análise pronta para quem você escolher.
- **Registro de tudo:** um banco de dados local guarda o que já foi feito, o que deu errado e quais foram os erros de cada análise.
- **Execução automática:** pode rodar sozinho, em horários definidos, pelo Agendador de Tarefas do Windows.

---

## 🧩 Como Funciona

```
        SEI
         │   1. coleta os processos
         ▼
    SEI-Agent
         │   2. envia os dados (pasta do OneDrive)
         ▼
  Power Automate  ──►  AI Builder (análise)
         │   3. a análise volta (pasta do OneDrive)
         ▼
    SEI-Agent
         │   4. corrige, confere e guarda
         ▼
  Teams + relatório
```

O Python não faz a análise: ela acontece no Power Automate, pelo AI Builder. A comunicação entre os dois é por duas pastas do SharePoint sincronizadas pelo OneDrive, uma para enviar e outra para receber.

---

## 📋 Pré-requisitos

- **Python** 3.10 ou superior
- **Windows**
- Acesso ao **SEI**
- **OneDrive** sincronizando as pastas de envio e de recebimento
- Endereço de envio do **Teams**, se quiser receber as análises por lá

---

## 🚀 Instalação

```powershell
cd SEI-Agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

---

## 📁 Estrutura de Arquivos

```
SEI-Agent/
│
├── main.py               # Programa principal
├── config.py             # Lê as configurações do .env
├── prompt.md             # Instruções da análise (cópia do prompt do AI Builder)
├── prompt_revisor.md     # Instruções para revisar uma análise
├── .env.example          # Modelo das configurações
│
├── sei/                  # Acesso ao SEI e senha
├── extratores/           # Leitura de anexos PDF e Word
├── automate/             # Envio, revisão e Teams
│   ├── entrada/          # Dados enviados para a análise
│   └── saida/            # Análises revisadas e relatórios
├── banco/                # Banco de dados e relatório
├── tests/                # Testes
└── logs/                 # Registro de cada execução
```

---

## 🔧 Configuração

Edite o arquivo `.env`, criado na instalação. O que ficar vazio usa o valor padrão. O `.env` não vai para o Git: não o compartilhe.

| Variável | Para que serve |
|---|---|
| `SEI_USUARIO` | Seu usuário do SEI |
| `SEI_ORGAO` / `SEI_UNIDADE` | Órgão e unidade em que o programa trabalha |
| `SEI_MODO` | `novos` (padrão): processos que chegaram depois da primeira execução. `marcador`: processos com o marcador abaixo |
| `SEI_MARCADOR` | Marcador dos processos a analisar, no modo `marcador` |
| `HEADLESS` | Mantenha `False`: com o navegador oculto o SEI trava |
| `TENTATIVAS_MAXIMAS` | Quantas falhas seguidas um processo aguenta antes de o programa deixá-lo de lado |
| `SHAREPOINT_PASTA_ENTRADA` | Pasta do OneDrive para onde os dados são enviados |
| `SHAREPOINT_PASTA_SAIDA` | Pasta do OneDrive de onde as análises são lidas |
| `SAIDA_ESPERA_MINUTOS` | Quanto esperar pelas análises |
| `TEAMS_WEBHOOK_URL` | Endereço de envio do Teams |
| `TEAMS_DESTINATARIOS` | E-mails de quem recebe a análise, separados por vírgula |

### Senha do SEI

A senha **não fica no `.env`**: ela é guardada no Gerenciador de Credenciais do Windows, protegida e ligada ao seu usuário do Windows. Cadastre uma vez:

```powershell
python -m sei.credenciais --cadastrar
```

Para trocar a senha, rode o mesmo comando de novo. `--verificar` diz se há senha guardada e `--apagar` a remove.

---

## 🎯 Como Usar

### Passo 1 — Cadastrar a senha
Preencha `SEI_USUARIO` no `.env` e rode o comando da seção anterior.

### Passo 2 — Testar com um processo
```powershell
python main.py --processo "SEI-000000/000000/2026"
```
Trabalha só nesse processo, sem olhar o modo nem o que já foi feito antes.

### Passo 3 — Executar normalmente
```powershell
python main.py
```
Escolhe os processos, envia para a análise e espera o resultado. No modo `novos`, a **primeira** execução só anota o que já existe e não envia nada.

| Opção | O que faz |
|---|---|
| `--processo "SEI-..."` | Trabalha só nesse processo |
| `--reanalisar` | Volta a analisar processos já feitos. No modo `novos`, pega **todos**: use com cuidado |
| `--sem-saida` | Não espera as análises (elas podem ser recebidas depois) |

### Passo 4 — Acompanhar
```powershell
python -m banco.relatorio
python -m banco.relatorio --processo "SEI-000000/000000/2026"
```
O relatório mostra o que já foi feito, o que está pendente, o que deu erro e as últimas análises. O registro de cada execução fica na pasta `logs`.

### Outros comandos

| Comando | Para que serve |
|---|---|
| `python -m automate.saidas` | Recebe, revisa e envia as análises novas que estiverem na pasta |
| `python -m automate.saidas --arquivo ANALISE.md` | Revisa só esse arquivo (serve também para reenviar ao Teams) |
| `python -m automate.saidas --sem-teams` | Revisa sem enviar ao Teams |
| `python -m automate.teams --teste` | Manda uma mensagem de teste pelo Teams |

---

## ⏰ Execução Agendada

Com a senha já cadastrada, o programa pode rodar sozinho. No PowerShell, ajuste o caminho do Python, o da pasta do projeto, os dias e os horários (um gatilho para cada horário):

```powershell
$pasta = "\\servidor\caminho\SEI-Agent"
$horas = '09:00', '11:00', '14:00', '16:00'
$gatilhos = foreach ($h in $horas) {
  New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $h
}
$acao = New-ScheduledTaskAction `
  -Execute "C:\caminho\do\python.exe" `
  -Argument "`"$pasta\main.py`"" -WorkingDirectory $pasta
$config = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
$quem = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName "SEI-Agent" -Action $acao -Trigger $gatilhos -Settings $config -Principal $quem
```

- Use o caminho de rede completo, e não a letra do disco mapeado.
- A tarefa só roda com o **mesmo usuário** que cadastrou a senha, e com ele logado. Pode estar com a tela bloqueada (Win+L), mas não pode ter saído da conta nem estar com o computador suspenso.
- O navegador abre uma janela a cada execução. Não use `HEADLESS=True`: com o navegador oculto o SEI trava.
- O computador precisa estar ligado e com o OneDrive aberto. Se ele reiniciar, a tarefa só volta a rodar depois que o usuário logar.
- Se uma execução falhar, a próxima tenta de novo. Se ainda estiver rodando quando chegar o horário seguinte, esse horário é pulado. O motivo de qualquer falha fica no log.
- Teste antes à mão.
- Para acompanhar: `(Get-ScheduledTaskInfo -TaskName "SEI-Agent").LastTaskResult` (`0` = ok, `1` = falha) e `python -m banco.relatorio`.

---

## 🧪 Testes

```powershell
pip install -r requirements-dev.txt
pytest -q
```

Os testes não acessam o SEI, o Teams nem o OneDrive de verdade.

---

## 🤝 Contribuição

Dúvidas, sugestões e problemas devem ser levados ao responsável pelo projeto. Se as instruções da análise mudarem, atualize o `prompt.md` e o prompt do AI Builder, no Power Automate.

---

## 👤 Autor

**Matheus Ribeiro** · [@matheusrbr11](https://github.com/matheusrbr11)

---

<div align="center">
  <sub>SEI-Agent &nbsp;|&nbsp; Autor: <a href="https://github.com/matheusrbr11">Matheus Ribeiro</a></sub>
</div>
