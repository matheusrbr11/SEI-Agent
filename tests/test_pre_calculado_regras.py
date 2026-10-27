from datetime import datetime, timezone

from automate.exportador import calcular_pre_calculado, preparar_para_automate
from sei.modelos import MOTIVO_PLANILHA, DocumentoSEI, ProcessoSEI

HOJE = datetime(2026, 10, 22, 11, 13, tzinfo=timezone.utc)


def _interno(unidade, texto="", nome="Doc"):
    return DocumentoSEI(nome=nome, unidade=unidade, texto=texto, origem_texto="sei_html")


def _externo(unidade, texto="", nome="Anexo"):
    return DocumentoSEI(nome=nome, unidade=unidade, texto=texto, origem_texto="arquivo")


def _assinado(data):
    return f"Documento assinado eletronicamente por Fulano, Chefe, em {data}, às 10:00, conforme horário oficial."


def _calcular(*docs):
    return calcular_pre_calculado(ProcessoSEI(numero="P", documentos=list(docs)), HOJE)


# --- situação de resposta

def test_situacao_sem_manifestacao_e_definitiva():
    dados = _calcular(_interno("SEFAZ/SUBTES", "À SUPCONFI,\nEfetuar"))
    assert dados["situacao_resposta"] == {
        "valor": "SEM MANIFESTAÇÃO ANTERIOR",
        "definitivo": True,
        "motivo": "Nenhum documento da SUPCONFI consta no processo.",
    }


def test_situacao_nova_demanda_quando_nossa_ultima_manifestacao_e_anterior_ao_demandante():
    dados = _calcular(
        _interno("SEFAZ/SUPCONC", "À SUBTES, resposta", "Nossa resposta"),
        _interno("SEFAZ/SUBTES", "À SEFAZ/SUPCONFI,\nNovo pedido", "Novo despacho"),
    )
    situacao = dados["situacao_resposta"]
    assert situacao["valor"] == "NOVA DEMANDA APÓS RESPOSTA"
    assert situacao["definitivo"] is False  # a IA pode corrigir se o despacho só der ciência
    assert "Nossa resposta (ordem 1)" in situacao["motivo"] and "ordem 2" in situacao["motivo"]


def test_situacao_fica_para_a_ia_quando_respondemos_depois_do_demandante():
    dados = _calcular(
        _interno("SEFAZ/SUBTES", "À SEFAZ/SUPCONFI,\nPedido", "Pedido"),
        _interno("SEFAZ/SUPCONC", "À SUBTES, resposta", "Nossa resposta"),
    )
    situacao = dados["situacao_resposta"]
    assert situacao["valor"] is None and situacao["definitivo"] is False
    assert "posterior" in situacao["motivo"]


def test_situacao_sem_demandante_e_nula():
    assert _calcular(_interno("SEFAZ/SUPCONC", "À SUBTES"))["situacao_resposta"] is None


# --- linha do tempo: destinatário e papel

def test_linha_do_tempo_destinatarios_e_papeis_decididos_por_regra():
    dados = _calcular(
        _externo("SEFAZ/SUBCINT", "Termo do TCE", "Termo"),  # ordem 1, externo
        _interno("SEFAZ/SUBTES", "Gov\nÀ SEFAZ/SUPAEF,\nÀ SEFAZ/SUBCINT,\nEncaminho", "Encaminha"),  # IA decide o papel
        _externo("SEFAZ/COOCB", "Planilha anexada", "Anexo posterior"),  # externo depois da ordem 1
        _interno("SEFAZ/SUPCONC", "À SUBTES,\nResposta", "Resposta"),  # nossa
        _interno("SEFAZ/SUBTES", "Gov\nÀ SEFAZ/SUPCONC,\nPedido", "Pedido"),  # endereçado a nós
        _interno("SEFAZ/SUBTES", "Gov\nÀ Chefia da SUPCONFI,\nCiência", "Chefia"),  # chefia não é a unidade
    )
    por_ordem = {item["ordem"]: item for item in dados["linha_do_tempo"]}
    assert (por_ordem[1]["destinatario"], por_ordem[1]["papel"]) == ("documento externo", "origem")
    assert por_ordem[2]["destinatario"] == "À SEFAZ/SUPAEF / À SEFAZ/SUBCINT"
    assert por_ordem[2]["papel"] is None
    assert (por_ordem[3]["destinatario"], por_ordem[3]["papel"]) == ("documento externo", "informação")
    assert por_ordem[4]["papel"] == "resposta da SUPCONFI"
    assert por_ordem[5]["papel"] == "pedido à SUPCONFI"
    assert por_ordem[6]["papel"] is None


def test_documento_nosso_nunca_e_pedido_a_nos_e_unidade_vazia_vira_nao_informada():
    dados = _calcular(_interno(None, "Gov\nÀ SUPCONFI,\nAlgo", "Sem unidade"))
    item = dados["linha_do_tempo"][0]
    assert item["unidade"] == "Unidade não informada"
    assert item["papel"] == "pedido à SUPCONFI"  # a regra de pedido vem antes da de origem


def test_documento_interno_sem_enderecamento_fica_sem_destinatario():
    item = _calcular(_interno("SEFAZ/SUBTES", "Gov\nSem endereço\nTexto", "A"), _interno("SEFAZ/SUBTES", "x", "B"))["linha_do_tempo"][1]
    assert item["destinatario"] is None and item["papel"] is None


# --- data de assinatura, solicitantes e competência

def test_demandante_traz_data_de_assinatura_e_texto_do_solicitante():
    dados = _calcular(_interno("SEFAZ/SUBTES", "Gov\nÀ SEFAZ/SUPCONFI,\n" + _assinado("09/09/2026"), "Despacho 25"))
    assert dados["despacho_demandante"]["data_assinatura"] == "09/09/2026"
    assert dados["solicitante_demanda_texto"] == "SEFAZ/SUBTES, conforme Despacho 25 (ordem 1), de 09/09/2026"
    assert dados["linha_do_tempo"][0]["data_assinatura"] == "09/09/2026"


def test_solicitante_demanda_texto_sem_data_de_assinatura():
    dados = _calcular(_interno("SEFAZ/SUBTES", "Gov\nÀ SEFAZ/SUPCONFI,", "Despacho"))
    assert dados["solicitante_demanda_texto"].endswith("de data de assinatura não identificada nos documentos fornecidos")


def test_externo_nao_tem_data_de_assinatura():
    dados = _calcular(_externo("SEFAZ/SUBCINT", _assinado("01/01/2026")))
    assert dados["linha_do_tempo"][0]["data_assinatura"] is None


def test_solicitante_origem_interno_e_externo():
    interno = _calcular(_interno("SEFAZ/SUPGO", "x"))["solicitante_origem"]
    assert interno == {"via": "SEFAZ/SUPGO", "texto": "SEFAZ/SUPGO", "dominios_de_email": []}
    externo = _calcular(_externo("SEFAZ/SUBCINT", "Timbre do TCE"))["solicitante_origem"]
    assert externo == {"via": "SEFAZ/SUBCINT", "texto": None, "dominios_de_email": []}  # o órgão sai do timbre, pela IA
    assert _calcular()["solicitante_origem"] is None


def test_solicitante_origem_externo_traz_dominios_de_email_como_pista():
    texto = "Enviar para <fisc59_2026@tcerj.tc.br> e para Fulano@TCERJ.tc.br, ou para fulano@fazenda.rj.gov.br."
    origem = _calcular(_externo("SEFAZ/SUBCINT", texto))["solicitante_origem"]
    assert origem["dominios_de_email"] == ["tcerj.tc.br", "fazenda.rj.gov.br"]


def test_competencia_pronta_so_quando_o_pedido_e_enderecado_a_nos():
    enderecado = _calcular(_interno("SEFAZ/SUBTES", "Gov\nÀ SEFAZ/SUPCONFI,", "Despacho 25"))
    assert enderecado["competencia"] == (
        "COMPETÊNCIA IDENTIFICADA. Pedido endereçado expressamente à SUPCONFI no Despacho 25 (ordem 1)."
    )
    citado = _calcular(_interno("SEFAZ/SUBTES", "Segue para providências da SUPCONC no mês"))
    assert citado["competencia"] is None
    assert _calcular()["competencia"].startswith("NÃO FOI POSSÍVEL DETERMINAR")


# --- prazos

def test_prazos_vencido_no_prazo_e_chegada():
    dados = _calcular(
        _externo("SEFAZ/SUBCINT", "Prorrogação do prazo até o dia 06/08/2026.", "Prorrogação"),
        _interno(
            "SEFAZ/SUBTES",
            "Gov\nÀ SEFAZ/SUPCONFI,\nPrazo: 30/10/2026\n" + _assinado("09/09/2026"),
            "Despacho 2",
        ),
    )
    assert [p["data"] for p in dados["prazos_encontrados"]] == ["06/08/2026", "30/10/2026"]  # em ordem de data
    vencido, no_prazo = dados["prazos_encontrados"]
    assert (vencido["situacao"], vencido["dias"], vencido["chegada"]) == ("VENCIDO", 77, "depois")
    assert [(f["ordem"], f["documento"]) for f in vencido["fontes"]] == [(1, "Prorrogação")]
    assert (no_prazo["situacao"], no_prazo["dias"], no_prazo["chegada"]) == ("NO PRAZO", 8, "antes")


def test_mesma_data_em_varios_documentos_vira_um_prazo_com_varias_fontes():
    dados = _calcular(
        _externo("SEFAZ/SUBCINT", "Prazo: 06/08/2026", "Termo"),
        _interno("SEFAZ/SUBTES", "Gov\nÀ SEFAZ/SUPCONFI,\nObservado o prazo final de até 06/08/26", "Despacho"),
    )
    (prazo,) = dados["prazos_encontrados"]
    assert [f["ordem"] for f in prazo["fontes"]] == [1, 2]


def test_prazo_na_propria_data_de_referencia_ainda_esta_no_prazo():
    dados = _calcular(_externo("SEFAZ/SUBCINT", "Prazo: 22/10/2026"))
    assert [(p["situacao"], p["dias"]) for p in dados["prazos_encontrados"]] == [("NO PRAZO", 0)]  # hoje conta como no prazo


def test_prazo_sem_data_de_chegada_deixa_chegada_nula():
    dados = _calcular(_externo("SEFAZ/SUBCINT", "Prazo: 22/10/2026"))
    assert dados["prazos_encontrados"][0]["chegada"] is None


def test_sem_prazos_lista_vazia():
    assert _calcular(_interno("SEFAZ/SUBTES", "Nada"))["prazos_encontrados"] == []


# --- alertas automáticos

def test_alerta_quando_demandante_apenas_cita_nossa_unidade():
    dados = _calcular(_interno("SEFAZ/SUBTES", "Segue para providências da SUPCONC", "Despacho"))
    assert dados["alertas_automaticos"] == [
        "O despacho demandante (Despacho, ordem 1) não é endereçado expressamente à nossa unidade; "
        "apenas cita a SUPCONFI no texto."
    ]


def test_alerta_quando_nenhum_documento_cita_nossa_unidade():
    dados = _calcular(_interno("SEFAZ/SUBTES", "Nada", "Despacho"))
    assert "foi adotado como despacho demandante e precisa ser confirmado" in dados["alertas_automaticos"][0]


def test_alerta_sem_despacho_demandante():
    dados = _calcular(_interno("SEFAZ/SUPCONC", "À SUBTES"))
    assert dados["alertas_automaticos"] == [
        "Nenhum documento de outra unidade foi identificado como despacho demandante; não há providência a propor."
    ]


def test_alertas_de_documentos_sem_texto_e_planilhas():
    dados = _calcular(
        _interno("SEFAZ/SUBTES", "Gov\nÀ SEFAZ/SUPCONFI,", "Despacho"),
        DocumentoSEI(nome="Anexo vazio", unidade="SEFAZ/A", origem_texto="arquivo"),
        DocumentoSEI(nome="Planilha", unidade="SEFAZ/A", origem_texto="arquivo", motivo_sem_texto=MOTIVO_PLANILHA),
    )
    assert dados["alertas_automaticos"] == [
        "Documentos sem texto extraído: ordem 2 - Anexo vazio.",
        "Documentos não lidos (planilha Excel não lida): ordem 3 - Planilha.",
    ]


def test_alerta_especifico_quando_o_demandante_esta_sem_texto_sem_repetir_na_lista():
    dados = _calcular(DocumentoSEI(nome="Despacho", unidade="SEFAZ/SUBTES", origem_texto="sei_html"))
    assert len(dados["alertas_automaticos"]) == 2  # sem texto + "não é endereçado" (não dá para saber)
    assert any("sem texto extraído; a análise do pedido pode estar incompleta" in a for a in dados["alertas_automaticos"])
    assert not any(a.startswith("Documentos sem texto extraído") for a in dados["alertas_automaticos"])


def test_sem_problemas_nao_ha_alertas():
    dados = _calcular(_interno("SEFAZ/SUBTES", "Gov\nÀ SEFAZ/SUPCONFI,\nPedido", "Despacho"))
    assert dados["alertas_automaticos"] == []


# --- payload final

def test_payload_so_traz_supconfi_mas_preserva_email():
    processo = ProcessoSEI(
        numero="P",
        documentos=[
            _interno("SEFAZ/SUBTES", "Gov\nÀ SEFAZ/SUPCONC,\nResponder em supconc.subtes@fazenda.rj.gov.br", "Despacho"),
            _interno("SEFAZ/SUPCONC", "À SUBTES, Superintendente SUPCONC", "Resposta"),
        ],
    )
    dados = preparar_para_automate(processo)
    assert "SUPCONC" not in str(dados).replace("supconc.subtes@fazenda.rj.gov.br", "")
    assert "supconc.subtes@fazenda.rj.gov.br" in dados["documentos"][0]["texto"]
    assert dados["pre_calculado"]["despacho_demandante"]["criterio"] == "enderecado_a_nos"
    assert [m["ordem"] for m in dados["pre_calculado"]["manifestacoes_nossas"]] == [2]


def test_planilha_aparece_com_o_motivo_no_texto():
    processo = ProcessoSEI(
        numero="P",
        documentos=[DocumentoSEI(nome="Planilha", origem_texto="arquivo", motivo_sem_texto=MOTIVO_PLANILHA)],
    )
    dados = preparar_para_automate(processo)
    assert dados["documentos"][0]["texto"] == "[SEM TEXTO EXTRAÍDO: planilha Excel não lida]"
    assert dados["controle"]["documentos_sem_texto"] == ["Planilha"]
