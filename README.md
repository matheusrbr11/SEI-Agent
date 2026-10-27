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

Edite `.env` e confirme `SEI_ORGAO`, `SEI_UNIDADE`, marcador e usuário.

## Execução

Teste controlado com um processo:

```powershell
python main.py --processo "SEI-040009/001813/2026" --reanalisar
```

Execução normal pelo marcador configurado:

```powershell
python main.py
```

Com `SHAREPOINT_PASTA_SAIDA` configurada, depois de entregar os JSONs ao SharePoint o agente **fecha o navegador** e fica aguardando as análises dos processos entregues aparecerem na pasta de saída (até `SAIDA_ESPERA_MINUTOS`, padrão 5, olhando a cada `SAIDA_INTERVALO_SEGUNDOS`, padrão 20). Só são analisadas as análises **novas dos processos desta execução**: o que já estava na pasta antes de começar (mesmo do mesmo processo) e as análises de outros processos são ignorados, sem serem corrigidos, validados nem enviados. Se o processo já tem análise na pasta, o agente espera a versão nova dele (uma versão é nova quando o conteúdo é diferente). Cada análise que chega é corrigida e validada na hora (veja "Leitura da saída") e o resultado vai para `automate/saida`. As que não chegarem a tempo viram um aviso no log, e `python -m automate.saidas` pega depois. `Ctrl+C` encerra só a espera. Para pular tudo isso: `python main.py --sem-saida`.

## Envio ao SharePoint (sem API REST)

A pasta `5 - Automação/05 - Agente/entrada` do site SUBTES está sincronizada no OneDrive. Preencha `SHAREPOINT_PASTA_ENTRADA` no `.env` com o caminho local dessa pasta (ex.: `C:\Users\<usuario>\OneDrive - SEFAZ-RJ\SUBTES - SUPCONC\5 - Automação\05 - Agente\entrada`). Depois de gerar `automate/entrada/ENTRADA_*.json`, o agente copia o arquivo para essa pasta e o cliente do OneDrive faz o upload; o fluxo é disparado pelo arquivo novo. Se a pasta não existir (OneDrive fechado/não sincronizado) ou a cópia falhar, o processo fica com status `erro_envio` e é reenviado na próxima execução. Variável vazia = não copia.

## Leitura da saída (análises do Power Automate)

A pasta `5 - Automação/05 - Agente/saida` também é sincronizada no OneDrive. Preencha `SHAREPOINT_PASTA_SAIDA` no `.env` com o caminho local dela e rode:

```powershell
python -m automate.saidas            # só as análises novas
python -m automate.saidas --refazer  # todas de novo
python -m automate.saidas --arquivo ANALISE_X.md
```

Para cada `.md` o agente acha o JSON de entrada pelo número da seção "Processo" (o nome do arquivo não precisa trazê-lo), corrige o que é só **formato** ou **nome de unidade** e confere o resto com o `validador`:

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

No `main.py`, só vai ao Teams a análise **nova** dos processos daquela execução (as demais da pasta de saída nem são analisadas). Já `python -m automate.saidas` envia toda análise nova que encontrar. `--refazer` e `--sem-teams` não enviam. Para conferir a configuração sem uma análise, rode `python -m automate.teams --teste`, que manda uma mensagem de teste aos destinatários. Falha no envio é registrada no log e nunca interrompe a coleta. Os testes nunca enviam mensagens de verdade (`tests/conftest.py` desliga o Teams).

## Pastas

- `automate/entrada`: arquivos JSON que disparam o fluxo.
- `automate/saida`: análises já corrigidas e conferidas pelo agente (veja "Leitura da saída" abaixo), cada uma com seu `.validacao.txt`.
- `automate/erros`: registros criados pelo ramo de falha do fluxo.
- `downloads`: anexos baixados temporariamente.
- `banco/agente.db`: checkpoint local.
- `logs`: logs de execução.

## Configuração do Power Automate

Veja `GUIA_POWER_AUTOMATE.md`. O prompt pronto está em `PROMPT_POWER_AUTOMATE.txt`.

## Testes locais

```powershell
pytest -q
```
