# SEI-Agent + Power Automate

Projeto para coletar processos do SEI-RJ com `jupiter-subtes` e exportar um JSON para análise automática no Power Automate/AI Builder.

## Fluxo

```text
SEI -> Jupiter -> ProcessoSEI -> automate/entrada/*.json
    -> cópia para a pasta do SharePoint sincronizada pelo OneDrive (sem API/webhook)
    -> Power Automate (gatilho "Quando um arquivo é criado") -> Run a prompt -> análise .md
```

O JSON traz o bloco `pre_calculado`, calculado por regra fixa em `automate/exportador.py` (e `automate/extracao.py`), que o `prompt.md` manda a IA usar sem recalcular:

- data de referência, despacho demandante (com a data de assinatura = chegada à nossa unidade), solicitante da demanda (já em frase pronta) e nível da demanda;
- solicitante origem (a unidade, quando o documento de ordem 1 é interno);
- situação de resposta (a parte objetiva) e competência (quando decorre do endereçamento);
- linha do tempo completa, com destinatário (linhas "À / Ao / Com vistas à"), data de assinatura e o papel dos documentos que têm regra (a IA a usa só para consulta; ela não entra na resposta);
- prazos encontrados nos textos, já comparados com a data de referência e com a chegada (situação, dias e documentos que os citam);
- alertas objetivos (despacho demandante sem endereçamento expresso, documentos sem texto, planilhas não lidas).

Todo o conteúdo enviado à IA usa o nome atual das unidades que mudaram de nome: SUPCONC → SUPCONFI, SUPGO → SUPHOB e SUPAEF → SUPADFIN. E-mails como `supconc.subtes@...` e os nomes de documentos ficam como na fonte. Planilhas Excel da árvore não são clicadas (o navegador as baixaria); entram na lista como "[SEM TEXTO EXTRAÍDO: planilha Excel não lida]".

Depois que o Power Automate gera a análise (`automate/saida/*.md`), confira-a contra o JSON de entrada:

```powershell
python -m automate.validador automate\saida\ANALISE_X.md automate\entrada\ENTRADA_X.json
```

A análise tem 9 seções (`##`): Processo, Solicitante Origem, Solicitante Demanda, Contexto, Demanda, Pendências, Informações Relevantes, Proposta (`### Roteiro` e `### Despacho`) e Alertas. Cada `ERRO` é a análise contrariando o que o sistema calculou ou o formato (seções fora do formato, nomes antigos de unidades, campos técnicos, Solicitante Demanda com o nível, situação, prazo, competência, tipo e roteiro da proposta, alertas copiados e linhas "Preencher:"); `AVISO` pede só uma olhada.

O Python **não chama a IA** e não altera o processo. A IA fica no Power Automate e a saída é uma proposta sujeita à revisão humana.

## Instalação no Windows

```powershell
cd "Z:\Programas da SUPCONC\SEI-Agent"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

Para desenvolver e rodar os testes, instale `requirements-dev.txt` no lugar (ele inclui o `requirements.txt` e acrescenta o `pytest`). As versões do `requirements.txt` estão fixadas; só a `jupiter-subtes` fica com `>=`, porque é uma biblioteca interna, atualizada à parte (`pip install --upgrade jupiter-subtes`).

## Senha do SEI

A senha fica no **Gerenciador de Credenciais do Windows** (biblioteca `keyring`), criptografada e ligada ao usuário do Windows que a cadastrou. Ela nunca vai para o `.env`, o banco nem os logs. Cadastre uma vez, com `SEI_USUARIO` preenchido no `.env`:

```
python -m sei.credenciais --cadastrar   # pede a senha duas vezes e guarda; também serve para trocá-la
python -m sei.credenciais --verificar   # diz se há senha guardada, sem mostrá-la
python -m sei.credenciais --apagar
```

Na execução, o agente usa a senha guardada. Sem ela, **só pergunta se houver alguém no terminal**; em execução agendada, sem terminal, ele termina com código `1` e o log diz como cadastrar. Quando a senha do SEI mudar, rode `--cadastrar` de novo. No Agendador de Tarefas, a tarefa precisa rodar **com o mesmo usuário do Windows** que cadastrou a senha, e não funciona como `SYSTEM`.

## Configuração (`.env`)

Edite o `.env` (copiado de `.env.example`; ele está no `.gitignore`, não o versione nem o compartilhe). A senha do SEI não fica nele: veja "Senha do SEI" abaixo. Variável ausente ou vazia = valor padrão. Valor que ainda é o texto-modelo do `.env.example` (começa com `<`, como `<seu usuário do SEI>`) conta como não preenchido, e o agente avisa no log quais variáveis estão assim. Número ou `True/False` inválido faz o programa parar na partida, dizendo qual variável está errada.

| Variável | Padrão | Para que serve |
|---|---|---|
| `SEI_USUARIO` | (pergunta ao executar, se houver alguém no terminal) | Usuário do SEI; também é a chave da senha guardada no Windows |
| `SEI_ORGAO` | `SEFAZ` | Órgão no login |
| `SEI_UNIDADE` | `SUPCONFI` | Unidade em que o agente trabalha |
| `SEI_MODO` | `marcador` | `marcador` (processos com o marcador abaixo) ou `novos` (processos que surgirem depois da primeira execução) |
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

## Execução

Teste controlado com um processo:

```powershell
python main.py --processo "SEI-040009/001813/2026"
```

Execução normal pelo modo configurado em `SEI_MODO`:

```powershell
python main.py
```

Opções: `--processo` trabalha só nesse processo e ignora o modo, o marcador e o banco; `--reanalisar` não descarta os processos que o banco já conhece (no modo `novos` isso pega **todo** o Controle de Processos: use com cuidado); `--sem-saida` não espera as análises.

**Código de saída:** `0` se todos os processos foram coletados e entregues (ou não havia nenhum); `1` se a autenticação falhou ou se algum processo teve falha de coleta ou de entrega nesta execução. Um processo que o agente já desistiu de tentar (veja "Banco de dados") não conta como falha da execução, mas aparece no `python -m banco.relatorio`. Análise com `ERRO` de validação não altera o código de saída do `main.py`: ela é entregue ao Teams e fica no relatório `.validacao.txt`.

Com `SHAREPOINT_PASTA_SAIDA` configurada, depois de entregar os JSONs ao SharePoint o agente **fecha o navegador** e fica aguardando as análises dos processos entregues aparecerem na pasta de saída (até `SAIDA_ESPERA_MINUTOS`, padrão 5, olhando a cada `SAIDA_INTERVALO_SEGUNDOS`, padrão 20). Só são analisadas as análises **novas dos processos desta execução**: o que já estava na pasta antes de começar (mesmo do mesmo processo) e as análises de outros processos são ignorados, sem serem corrigidos, validados nem enviados. Se o processo já tem análise na pasta, o agente espera a versão nova dele (uma versão é nova quando o conteúdo é diferente). Cada análise que chega é corrigida e validada na hora (veja "Leitura da saída") e o resultado vai para `automate/saida`. As que não chegarem a tempo viram um aviso no log, e `python -m automate.saidas` pega depois. `Ctrl+C` encerra só a espera. Para pular tudo isso: `python main.py --sem-saida`.

## Envio ao SharePoint (sem API REST)

A pasta `5 - Automação/05 - Agente/entrada` do site SUBTES está sincronizada no OneDrive. Preencha `SHAREPOINT_PASTA_ENTRADA` no `.env` com o caminho local dessa pasta (ex.: `C:\Users\<usuario>\OneDrive - SEFAZ-RJ\SUBTES - SUPCONC\5 - Automação\05 - Agente\entrada`). Depois de gerar `automate/entrada/ENTRADA_*.json`, o agente copia o arquivo para essa pasta e o cliente do OneDrive faz o upload; o fluxo é disparado pelo arquivo novo. Se a pasta não existir (OneDrive fechado/não sincronizado) ou a cópia falhar, o processo fica com status `erro_envio` e é reenviado na próxima execução **sem ser coletado de novo**: o JSON já gerado é reaproveitado (se o arquivo ainda existir). Variável vazia = não copia.

## Leitura da saída (análises do Power Automate)

A pasta `5 - Automação/05 - Agente/saida` também é sincronizada no OneDrive. Preencha `SHAREPOINT_PASTA_SAIDA` no `.env` com o caminho local dela e rode:

```powershell
python -m automate.saidas            # só as análises novas
python -m automate.saidas --refazer  # todas de novo
python -m automate.saidas --arquivo ANALISE_X.md
```

Para cada `.md` o agente acha o JSON de entrada pelo número da seção "Processo" (o nome do arquivo não precisa trazê-lo), corrige o que é só **formato** ou **nome de unidade** e confere o resto com o `validador`:

- a marcação `<documents>` ... `</documents>` que a IA às vezes põe em volta da análise é removida (no Teams ela fazia o `## Processo` aparecer como texto cru);
- `## Roteiro` / `## Despacho` viram `###` dentro de Proposta;
- linhas "Preencher:" sem nenhum `[PREENCHER]` na análise saem dos Alertas;
- alertas ganham `- ` e uma linha em branco entre eles;
- despacho: linha em branco após o vocativo e entre parágrafos, e frase partida em dois parágrafos volta a ser uma só;
- nomes antigos de unidades (SUPCONC, SUPGO, SUPAEF) são trocados pelos atuais, fora de e-mails e de nomes de documentos.

A pasta do OneDrive **só é lida** (nada é gravado nela, para não disparar o fluxo). O resultado vai para `automate/saida`: `<nome>.md` corrigido e `<nome>.validacao.txt` com as correções feitas e os `ERRO`/`AVISO` que restam. Erros de conteúdo (e-mail trocado, prazo, situação, seção ausente) não são corrigidos: aparecem no relatório para revisão humana. O código de saída é 1 se houver algum `ERRO`.

## Envio da análise pelo Teams

Cada análise corrigida pode ser enviada a uma pessoa pelo Teams, por um **webhook** (o JSON enviado tem o formato de `GraphAPI.enviar_mensagem` da jupiter: `{"destinatarios": [...], "mensagem": "..."}`). O webhook não aceita anexo, então a análise vai **como texto**: um cabeçalho mínimo (`SEI-Agent` em texto simples e uma linha `---`, necessários para o Teams formatar o `## Processo` como título; `#` ou negrito no cabeçalho desfazem a formatação) e, em seguida, o conteúdo do `.md` corrigido, sem lista de problemas nem caminho de arquivo. Textos acima de `TEAMS_LIMITE_CARACTERES` (padrão 25000) são cortados, e o corte fica registrado no log; o arquivo completo continua em `automate/saida`. Os erros e avisos da validação não vão na mensagem: ficam em `<nome>.validacao.txt`, ao lado do `.md` corrigido.

A configuração fica no `.env` (modelo em `.env.example`). A URL do webhook contém uma assinatura que funciona como senha, e o `.env` está no `.gitignore`: não o versione nem o compartilhe.

- `TEAMS_WEBHOOK_URL`: URL do webhook.
- `TEAMS_DESTINATARIOS`: e-mail(s) de quem recebe a análise, separados por vírgula.

Sem webhook ou sem destinatário, nada é enviado.

No `main.py`, só vai ao Teams a análise **nova** dos processos daquela execução (as demais da pasta de saída nem são analisadas). Já `python -m automate.saidas` envia toda análise nova que encontrar. `--refazer` e `--sem-teams` não enviam. Para conferir a configuração sem uma análise, rode `python -m automate.teams --teste`, que manda uma mensagem de teste aos destinatários. Falha de rede, de certificado SSL, do servidor (5xx) ou limite de uso (429) é tentada até 3 vezes (pausas de 5 e 15 s); erro 4xx não é repetido. Se nenhuma tentativa funcionar, o erro vai para o log (sem a chave `sig=` do webhook, que é ocultada) e nunca interrompe a coleta; o banco guarda `teams_enviado = 0`, e `python -m automate.saidas --arquivo X.md` reenvia. Os testes nunca enviam mensagens de verdade (`tests/conftest.py` desliga o Teams).

## Banco de dados (`banco/agente.db`)

Três tabelas, criadas e atualizadas sozinhas (o banco antigo é migrado na primeira execução, sem perder as linhas):

- `processos`: uma linha por processo, com o estado atual. É ela que decide o que o agente pega na próxima execução.
- `execucoes`: uma linha por execução (`main.py` ou `automate.saidas`), com início, fim, modo, totais (selecionados, exportados, falhas, análises) e o código de saída. Uma execução sem `fim` indica que o programa caiu.
- `historico`: uma linha por acontecimento (selecionado, coleta, JSON gerado ou reaproveitado, entrega, análise, Teams, desistência), só acrescentada, nunca sobrescrita. Guarda mensagens curtas, nunca conteúdo de processo.

Status em `processos`:

| Status | Significa | O agente pega de novo? |
|---|---|---|
| `baseline` | Já existia na primeira execução do modo `novos` | Não |
| `exportado` | JSON gerado e entregue (ou o JSON ficou só local, se `SHAREPOINT_PASTA_ENTRADA` estiver vazia) | Não |
| `analisado` | A análise chegou e foi corrigida e validada; o caminho do `.md` fica em `arquivo_saida` e, se a validação teve `ERRO`, o resumo vai em `erro` | Não |
| `erro_coleta` | A coleta no SEI falhou | Sim, até `TENTATIVAS_MAXIMAS` falhas seguidas |
| `erro_envio` | O JSON foi gerado, mas a cópia para o SharePoint falhou | Sim, reaproveitando o JSON, até o mesmo teto |

A coluna `falhas_seguidas` conta os erros desde o último sucesso. Ao chegar a `TENTATIVAS_MAXIMAS`, o agente deixa o processo de lado, registra o aviso e o evento `desistiu`; para tentar de novo, use `--processo`. Um novo `exportado` começa um ciclo novo: os dados da análise anterior saem da linha, mas continuam no `historico`.

Para consultar sem abrir o SQLite:

```powershell
python -m banco.relatorio                                         # status, pendentes, desistências e últimas execuções
python -m banco.relatorio --processo "SEI-040009/001847/2026"     # o histórico de um processo
python -m banco.relatorio --horas 4 --execucoes 20                # pendentes há mais de 4 h; 20 execuções
```

## Pastas

- `automate/entrada`: arquivos JSON que disparam o fluxo.
- `automate/saida`: análises já corrigidas e conferidas pelo agente (veja "Leitura da saída" abaixo), cada uma com seu `.validacao.txt`.
- `automate/erros`: reservada para registros de falha do fluxo; o agente só cria a pasta e não grava nada nela.
- `downloads`: anexos baixados durante a coleta. A pasta de cada processo é apagada assim que o JSON de entrada é gerado. Só sobra ali o que pertence a processos cuja coleta falhou (anexos e o diagnóstico da árvore, com HTML e print de tela), para investigação; apague-o depois.
- `banco/agente.db`: banco SQLite do agente (veja "Banco de dados").
- `logs/execução`: logs das execuções do agente (e, em `erros`, só os de nível ERROR). `logs/tests`: logs das rodadas de `pytest` (um arquivo por rodada, e em `erros` o de nível ERROR); os testes nunca gravam em `logs/execução`.

## Configuração do Power Automate

O fluxo em si é configurado no Power Automate, fora deste projeto. Os prompts estão na raiz: `prompt.md` (a análise do processo) e `prompt_revisor.md` (a revisão de uma análise contra um checklist).

## Testes locais

```powershell
pip install -r requirements-dev.txt
pytest -q
```

Os testes não usam o SEI, o Teams nem o OneDrive de verdade. O log de cada rodada vai para `logs/tests`.

`tests/test_prompt.py` confere que o `prompt.md` continua de acordo com o validador (as 9 seções na ordem, `### Roteiro` e `### Despacho`, e os tipos de providência, competências e situações de resposta). Se ele falhar, o prompt e o `automate/validador.py` se afastaram: atualize um dos dois. Ele só enxerga o `prompt.md` deste repositório, então mantenha-o como cópia fiel do prompt que está no Power Automate.
