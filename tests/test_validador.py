import json

import pytest

from automate.exportador import preparar_para_automate
from automate.validador import main, validar_saida
from sei.modelos import DocumentoSEI, ProcessoSEI


def _entrada():
    assinatura = "Documento assinado eletronicamente por Fulano, Chefe, em 09/09/2026, às 18:46, conforme horário."
    processo = ProcessoSEI(
        numero="SEI-040005/000729/2026",
        documentos=[
            DocumentoSEI(
                nome="Termo", unidade="SEFAZ/SUBCINT", origem_texto="arquivo",
                texto="Rio de Janeiro. Prazo para atendimento: 06/08/2026.",
            ),
            DocumentoSEI(
                nome="Resposta", unidade="SEFAZ/SUPCONC", origem_texto="sei_html",
                texto="Gov\nÀ SUBTES:\nEm devolução.",
            ),
            DocumentoSEI(
                nome="Despacho", unidade="SEFAZ/SUBTES", origem_texto="sei_html",
                texto="Gov\nÀ SEFAZ/SUPCONFI,\nCiência.\n" + assinatura,
            ),
        ],
    )
    return preparar_para_automate(processo)


def _analise(entrada, **trocas):
    """A análise que a IA deveria devolver para esta entrada, montada a partir dos campos calculados."""
    pre = entrada["pre_calculado"]
    prazo = pre["prazos_encontrados"][0]
    despacho = pre["despacho_demandante"]
    tempo = f"VENCIDO há {prazo['dias']} dias" if prazo["situacao"] == "VENCIDO" else f"NO PRAZO, faltam {prazo['dias']} dias"
    partes = {
        "processo": entrada["processo"]["numero"],
        "origem": "Tribunal de Contas do Estado do Rio de Janeiro (TCE-RJ) (via SEFAZ/SUBCINT)",
        "solicitante": f"{pre['solicitante_demanda_texto']} ({pre['nivel_demanda']})",
        "contexto": "Resumo do histórico.",
        "demanda": (
            f"Dar ciência do documento, conforme Termo (ordem 1), encaminhado a nós pelo "
            f"{despacho['nome']} (ordem {despacho['ordem']})."
        ),
        "pendencias": "1. Dar ciência.",
        "situacao": f"{pre['situacao_resposta']['valor']} - Nossa resposta é a ordem 2.",
        "manifestacoes": "2 - Resposta - despacho - Devolução à SUBTES.",
        "prazo": (
            f"{prazo['data']} - prazo de atendimento (fonte: Termo, ordem 1) - {tempo} em {pre['data_referencia']} - "
            f"chegada a nós em {despacho['data_assinatura']} ({prazo['chegada']} do prazo)"
        ),
        "competencia": pre["competencia"],
        "tipo": "CIÊNCIA - O despacho só dá ciência.",
        "roteiro": "Não se aplica.",
        "despacho": "À SEFAZ/SUBTES,\n\nEm atenção ao despacho, damos ciência.",
        "alertas": "\n".join(pre["alertas_automaticos"]) or "Nenhum alerta.",
    }
    partes.update(trocas)
    return f"""## Processo
{partes['processo']}

## Solicitante Origem
{partes['origem']}

## Solicitante Demanda
{partes['solicitante']}

## Contexto
{partes['contexto']}

## Demanda
{partes['demanda']}

## Pendências
{partes['pendencias']}

## Informações Relevantes
- Situação de resposta: {partes['situacao']}
- Manifestações anteriores da SUPCONFI: {partes['manifestacoes']}
- Prazo: {partes['prazo']}
- Competência: {partes['competencia']}

## Proposta
Tipo: {partes['tipo']}

### Roteiro
{partes['roteiro']}

### Despacho
{partes['despacho']}

## Alertas
{partes['alertas']}
"""


def _problemas(**trocas):
    entrada = _entrada()
    return validar_saida(_analise(entrada, **trocas), entrada)


def _avisos(problemas):
    return [p for p in problemas if p.startswith("AVISO")]


# --- estrutura

def test_analise_correta_nao_tem_problemas():
    entrada = _entrada()
    assert validar_saida(_analise(entrada), entrada) == []


def test_secao_ausente_desconhecida_e_ordem():
    entrada = _entrada()
    base = _analise(entrada)
    assert validar_saida(base.replace("## Contexto\nResumo do histórico.\n\n", ""), entrada) == ["ERRO: seção ausente: Contexto"]
    com_linha_do_tempo = base + "\n## Linha do tempo\n1 - Termo\n"
    assert validar_saida(com_linha_do_tempo, entrada) == ["ERRO: seção fora do formato (remova ou mova o conteúdo): Linha do tempo"]
    trocada = base.replace("## Demanda", "## TEMP").replace("## Pendências", "## Demanda").replace("## TEMP", "## Pendências")
    assert "ERRO: as seções estão fora da ordem do formato" in validar_saida(trocada, entrada)
    assert _avisos(validar_saida("# ANÁLISE DO PROCESSO\n\n" + base, entrada)) == [
        "AVISO: título de nível 1 fora do formato: ANÁLISE DO PROCESSO"
    ]


def test_proposta_precisa_das_subsecoes_e_de_um_tipo_valido():
    entrada = _entrada()
    base = _analise(entrada)
    assert validar_saida(base.replace("### Roteiro\nNão se aplica.\n\n", ""), entrada) == [
        "ERRO: a Proposta não tem a subseção '### Roteiro'"
    ]
    assert _problemas(tipo="TALVEZ - Sei lá.") == ["ERRO: o Tipo da Proposta não começa por um dos valores do formato"]


# --- nomes de unidades e campos técnicos

def test_nome_antigo_de_unidade_na_saida():
    assert "ERRO: a análise usa SUPCONC; deve usar SUPCONFI (nome atual da unidade)" in _problemas(
        despacho="À SEFAZ/SUBTES,\n\nA SUPCONC dá ciência."
    )
    assert "ERRO: a análise usa SUPGO; deve usar SUPHOB (nome atual da unidade)" in _problemas(contexto="Enviado à SUPGO.")
    assert "ERRO: a análise usa SUPAEF; deve usar SUPADFIN (nome atual da unidade)" in _problemas(contexto="Enviado à SUPAEF.")


def test_nome_antigo_dentro_de_nome_de_documento_e_aceito():
    entrada = _entrada()
    entrada["documentos"][0]["nome"] = "Ofício SUPGO nº 1"
    analise = _analise(entrada, contexto="O Ofício SUPGO nº 1 foi enviado à SUPHOB.")
    assert validar_saida(analise, entrada) == []


def test_email_igual_ao_do_documento_e_aceito_mesmo_com_nome_antigo_de_unidade():
    entrada = _entrada()
    entrada["documentos"][0]["texto"] += " Respostas para supconc.subtes@fazenda.rj.gov.br."
    assert validar_saida(_analise(entrada, contexto="Responder a supconc.subtes@fazenda.rj.gov.br."), entrada) == []


def test_email_com_nome_de_unidade_trocado_e_erro():
    entrada = _entrada()
    entrada["documentos"][0]["texto"] += " Respostas para supconc.subtes@fazenda.rj.gov.br."
    problemas = validar_saida(_analise(entrada, contexto="Responder a supconfi.subtes@fazenda.rj.gov.br."), entrada)
    assert problemas == [
        "ERRO: e-mail que não consta nos documentos: supconfi.subtes@fazenda.rj.gov.br (a troca de nomes de "
        "unidades não vale para endereços de e-mail; copie-os como estão)"
    ]


def test_nome_de_campo_tecnico_na_saida():
    assert "ERRO: nome de campo técnico na análise: pre_calculado" in _problemas(contexto="Segundo o pre_calculado.")


# --- cabeçalho

def test_cabecalho_deve_copiar_o_que_o_sistema_calculou():
    assert any("não traz o número" in p for p in _problemas(processo="outro"))
    assert any("Solicitante Demanda deveria ser" in p for p in _problemas(solicitante="SEFAZ/SUBTES (SUPERIOR)"))
    assert "ERRO: o Solicitante Origem tem marcador entre colchetes" in _problemas(origem="Tribunal ([SIGLA]) (via SEFAZ/SUBCINT)")
    assert any("sem o trecho (via" in p for p in _problemas(origem="Tribunal de Contas (TCE-RJ)"))


def test_solicitante_demanda_sem_o_nivel_entre_parenteses_e_erro():
    entrada = _entrada()
    sem_nivel = _analise(entrada, solicitante=entrada["pre_calculado"]["solicitante_demanda_texto"])
    assert any("Solicitante Demanda deveria ser" in p for p in validar_saida(sem_nivel, entrada))


def test_contexto_com_mais_de_5_linhas_gera_aviso():
    contexto = "\n".join(f"Linha {i}." for i in range(1, 7))
    assert _avisos(_problemas(contexto=contexto)) == ["AVISO: o Contexto tem 6 linhas; o formato pede até 5"]


# --- demanda e pendências

def test_demanda_deve_citar_o_despacho_demandante_com_nome_e_ordem():
    problemas = _problemas(demanda="Dar ciência do Termo (ordem 1), encaminhado a nós pelo Despacho.")
    assert _avisos(problemas) == ["AVISO: a Demanda não cita o despacho demandante como 'Despacho (ordem 3)'"]
    assert _problemas(demanda="Providência específica não identificada nos documentos fornecidos: o despacho demandante pede apenas ciência.") == []


def test_pendencias_de_conferencia_ou_que_repetem_alertas_geram_aviso():
    problemas = _problemas(pendencias="1. Dar ciência.\n2. Conferir se as respostas chegaram.")
    assert _avisos(problemas) == [
        "AVISO: pendência que é ordem de conferência (pendência é o que impede ou condiciona a execução): "
        "2. Conferir se as respostas chegaram."
    ]
    problemas = _problemas(pendencias="1. Dar ciência.\n2. Documentos sem texto extraído: Anexo X.")
    assert _avisos(problemas) == [
        "AVISO: pendência repete um alerta do sistema (documentos sem texto ou não lidos): "
        "2. Documentos sem texto extraído: Anexo X."
    ]


# --- informações relevantes

def test_situacao_definitiva_e_provisoria():
    # NOVA DEMANDA APÓS RESPOSTA é provisória: a IA pode trocar por JÁ RESPONDIDO, se justificar
    assert _problemas(
        situacao="JÁ RESPONDIDO - Respondemos na ordem 2.",
        tipo="JÁ RESPONDIDO - Já atendido.",
        pendencias="Nenhuma pendência: a demanda já foi atendida no documento Resposta, ordem 2.",
        despacho="Não há providência a propor. A demanda já foi atendida no documento Resposta, ordem 2.",
    ) == []
    assert any("deveria ser NOVA DEMANDA" in p for p in _problemas(situacao="SEM MANIFESTAÇÃO ANTERIOR - Nada."))
    assert any("não começa por um dos valores" in p for p in _problemas(situacao="Respondido."))


def test_situacao_ausente_nas_informacoes_relevantes():
    entrada = _entrada()
    sem_situacao = "\n".join(l for l in _analise(entrada).splitlines() if not l.startswith("- Situação de resposta"))
    assert validar_saida(sem_situacao, entrada) == ["ERRO: faltou o item 'Situação de resposta' em Informações Relevantes"]


def test_competencia_pronta_deve_ser_copiada():
    assert any("Competência deveria ser" in p for p in _problemas(competencia="COMPETÊNCIA PARCIAL. Talvez."))


def test_manifestacoes_anteriores():
    assert any("não aparece em Manifestações anteriores" in p for p in _problemas(manifestacoes="Outra coisa."))
    assert any("'resposta da SUPCONFI' não é tipo" in p for p in _problemas(manifestacoes="2 - Resposta - resposta da SUPCONFI - Devolução."))


def test_manifestacoes_anteriores_quando_nao_ha_nenhuma():
    entrada = _entrada()
    entrada["pre_calculado"]["manifestacoes_nossas"] = []
    assert validar_saida(_analise(entrada, manifestacoes="nenhuma."), entrada) == []
    assert any("diz outra coisa" in p for p in validar_saida(_analise(entrada, manifestacoes="2 - Resposta"), entrada))


def test_prazo_situacao_dias_e_chegada_conferem_com_o_sistema():
    entrada = _entrada()
    prazo = entrada["pre_calculado"]["prazos_encontrados"][0]
    correto = _analise(entrada)
    assert validar_saida(correto.replace(f"há {prazo['dias']} dias", "há 3 dias"), entrada) == [
        f"ERRO: o prazo {prazo['data']} tem {prazo['dias']} dia(s) de diferença para a data de referência"
    ]
    assert validar_saida(correto.replace("VENCIDO", "NO PRAZO"), entrada) == [
        f"ERRO: o prazo {prazo['data']} está VENCIDO, e não NO PRAZO"
    ]
    assert any("a chegada a nós deveria ser" in p for p in validar_saida(correto.replace("(depois do prazo)", "(antes do prazo)"), entrada))
    desconhecido = correto.replace(f"Prazo: {prazo['data']}", "Prazo: 01/01/2030")
    assert any(p.startswith("AVISO: o prazo 01/01/2030 não está entre os extraídos") for p in validar_saida(desconhecido, entrada))


def test_prazo_nao_identificado():
    problemas = _problemas(prazo="não identificado.")
    assert _avisos(problemas) == [
        f"AVISO: o sistema encontrou 1 prazo(s) nos documentos ({_entrada()['pre_calculado']['prazos_encontrados'][0]['data']}), "
        "mas a análise diz 'Prazo: não identificado.'"
    ]
    assert any("não deve comparar a chegada" in p for p in _problemas(prazo="não identificado. Chegada a nós em 09/09/2026."))


# --- proposta

def test_execucao_exige_roteiro_numerado_e_despacho_de_retorno():
    roteiro = "1. Anexar aos autos.\n   - Origem dos documentos: caixa de e-mail (fonte: Termo, ordem 1)"
    despacho = "(usar somente após a execução)\n\nÀ SEFAZ/SUBTES,\n\nInformamos que anexamos."
    assert _problemas(tipo="EXECUÇÃO - Pede para anexar.", roteiro=roteiro, despacho=despacho) == []

    com_traco = _problemas(tipo="EXECUÇÃO - Pede para anexar.", roteiro="- Anexar aos autos.", despacho=despacho)
    assert "ERRO: EXECUÇÃO exige o Roteiro com passos numerados ('1.', '2.')" in com_traco
    assert "ERRO: o passo do Roteiro começa com '-'; use '1.', '2.'" in com_traco

    sem_recuo = "1. Anexar aos autos.\n- Valor: R$ 1,00"
    assert any("devem ficar recuadas" in p for p in _problemas(tipo="EXECUÇÃO - x.", roteiro=sem_recuo, despacho=despacho))

    sem_dado = "1. Anexar aos autos.\n   - Valor: Não identificado nos documentos fornecidos."
    assert any("linhas 'Não identificado'" in p for p in _problemas(tipo="EXECUÇÃO - x.", roteiro=sem_dado, despacho=despacho))

    sem_indicacao = "À SEFAZ/SUBTES,\n\nInformamos que anexamos."
    assert "ERRO: o Despacho de EXECUÇÃO deve trazer a indicação '(usar somente após a execução)'" in _problemas(
        tipo="EXECUÇÃO - x.", roteiro=roteiro, despacho=sem_indicacao
    )
    assert any("Roteiro com passos numerados" in p for p in _problemas(tipo="EXECUÇÃO - x.", roteiro="Não se aplica.", despacho=despacho))


def test_fora_de_execucao_o_roteiro_e_nao_se_aplica():
    assert "ERRO: fora de EXECUÇÃO o Roteiro deve ser apenas 'Não se aplica.'" in _problemas(roteiro="1. Fazer algo.")


def test_despacho_deve_comecar_por_a_solicitante_demanda():
    assert _avisos(_problemas(despacho="Em atenção ao despacho, damos ciência.")) == [
        "AVISO: o Despacho deveria começar por 'À [SOLICITANTE DEMANDA],'"
    ]


def test_tipo_e_situacao_ja_respondido_devem_bater():
    problemas = _problemas(situacao="JÁ RESPONDIDO - Feito.", pendencias="Nenhuma pendência: a demanda já foi atendida no documento X, ordem 2.")
    assert "ERRO: o Tipo da Proposta e a Situação de resposta não batem (JÁ RESPONDIDO vale para os dois)" in problemas
    problemas = _problemas(tipo="JÁ RESPONDIDO - Feito.")
    assert "ERRO: o Tipo da Proposta e a Situação de resposta não batem (JÁ RESPONDIDO vale para os dois)" in problemas


def test_ja_respondido_exige_pendencias_e_despacho_de_nenhuma_providencia():
    problemas = _problemas(situacao="JÁ RESPONDIDO - Feito.", tipo="JÁ RESPONDIDO - Feito.")
    assert any("seção Pendências não diz 'Nenhuma pendência" in p for p in problemas)
    assert any("o Despacho não é 'Não há providência a propor" in p for p in problemas)


# --- alertas

def test_alertas_automaticos_devem_ser_copiados():
    entrada = _entrada()
    entrada["pre_calculado"]["alertas_automaticos"] = ["Documentos sem texto extraído: ordem 9 - X."]
    assert validar_saida(_analise(entrada, alertas="Nenhum alerta."), entrada) == [
        "ERRO: alerta calculado pelo sistema ausente: Documentos sem texto extraído: ordem 9 - X."
    ]
    assert validar_saida(_analise(entrada, alertas="- Documentos sem texto extraído: ordem 9 - X."), entrada) == []


def test_alertas_genericos_ou_condicionais_geram_aviso():
    problemas = _problemas(
        alertas=(
            "- Conferir se tudo foi anexado.\n\n- Verificar o prazo.\n\n- Prazo vencido: conferir se há consequência.\n\n"
            "- Responsável a confirmar caso haja dúvida."
        )
    )
    assert len(_avisos(problemas)) == 4
    assert _problemas(alertas="- Prazo 06/08/2026 vencido há 81 dias.") == []


def test_alertas_devem_ter_marcador_e_linha_em_branco_entre_eles():
    assert _avisos(_problemas(alertas="Prazo vencido há 81 dias.")) == ["AVISO: cada alerta deve começar com '- '"]
    assert _avisos(_problemas(alertas="- Prazo vencido há 81 dias.\n- Documento ausente.")) == [
        "AVISO: nos Alertas, separe cada alerta do seguinte por uma linha em branco"
    ]


def test_demanda_e_despacho_com_linhas_coladas_ou_frase_partida():
    assert _avisos(_problemas(
        demanda="Dar ciência do Termo (ordem 1), encaminhado a nós pelo Despacho (ordem 3).\nOutra frase."
    )) == ["AVISO: na Demanda, cada frase deve ficar separada da seguinte por uma linha em branco"]
    assert _avisos(_problemas(despacho="À SEFAZ/SUBTES,\nEm atenção ao despacho, damos ciência.")) == [
        "AVISO: no Despacho, separe por uma linha em branco o vocativo, cada parágrafo e o fecho"
    ]
    partida = "À SEFAZ/SUBTES,\n\nEm atendimento ao despacho SEI nº 141137222,\n\nInformamos que damos ciência."
    assert _avisos(_problemas(despacho=partida)) == [
        "AVISO: no Despacho, a frase parece partida em dois parágrafos (termina em vírgula): "
        "Em atendimento ao despacho SEI nº 141137222,"
    ]


def test_preencher_confere_com_os_marcadores():
    com_marcador = "À SEFAZ/SUBTES,\n\nO documento nº [PREENCHER: nº do documento] foi gerado."
    assert any("não têm linhas 'Preencher: ...'" in p for p in _problemas(despacho=com_marcador))
    assert _problemas(
        despacho=com_marcador,
        alertas="- Preencher: nº do documento gerado no sistema (provável fonte: sistema onde foi gerado)",
    ) == []
    assert any(p.startswith("AVISO: há linhas 'Preencher: ...'") for p in _problemas(alertas="- Preencher: algo (provável fonte: x)"))


def test_linha_de_comando(tmp_path, capsys):
    entrada = _entrada()
    (tmp_path / "entrada.json").write_text(json.dumps(entrada), encoding="utf-8")
    (tmp_path / "ok.md").write_text(_analise(entrada), encoding="utf-8")
    (tmp_path / "ruim.md").write_text(_analise(entrada, processo="outro"), encoding="utf-8")
    assert main(["x", str(tmp_path / "ok.md"), str(tmp_path / "entrada.json")]) == 0
    assert "OK" in capsys.readouterr().out
    assert main(["x", str(tmp_path / "ruim.md"), str(tmp_path / "entrada.json")]) == 1
    assert "ERRO: a seção Processo" in capsys.readouterr().out
    assert main(["x"]) == 2
