from datetime import datetime, timezone

import pytest

from automate.exportador import (
    calcular_pre_calculado,
    classificar_nivel,
    localizar_despacho_demandante,
    preparar_para_automate,
)
from sei.modelos import DocumentoSEI, ProcessoSEI

HOJE = datetime(2026, 10, 22, 11, 13, tzinfo=timezone.utc)


def _doc(unidade, texto="", nome="Doc"):
    return DocumentoSEI(nome=nome, unidade=unidade, texto=texto)


def _calcular(*docs):
    return calcular_pre_calculado(ProcessoSEI(numero="P", documentos=list(docs)), HOJE)


@pytest.mark.parametrize(
    "unidade, esperado",
    [
        ("SEFAZ/SUBTES", "SUPERIOR"),
        ("SEFAZ/SUBAFIN", "SUPERIOR"),
        ("SUBAFIN", "SUPERIOR"),
        ("SEFAZ/COOCB", "SUBORDINADA"),
        ("SEFAZ/COOCONC", "SUBORDINADA"),
        ("SEFAZ/SUPGO", "INTERNA"),
        ("SEFAZ/COOPNC", "INTERNA"),  # outras coordenadorias não são subordinadas
        ("SEFAZ/SUBTESOURO", "INTERNA"),  # sigla exata, não substring
        ("SECC/CHEGAB", "EXTERNA"),
        ("TCE-RJ", "EXTERNA"),
        ("", None),
        (None, None),
    ],
)
def test_nivel_da_demanda_pela_ordem_das_regras(unidade, esperado):
    assert classificar_nivel(unidade) == esperado


def test_despacho_demandante_e_o_ultimo_enderecado_a_nos():
    dados = _calcular(
        _doc("SEFAZ/CHEGAB", "Ofício externo"),
        _doc("SEFAZ/SUBTES", "Timbre\nÀ SUPCONC,\nPedido antigo", "Despacho A"),
        _doc("SEFAZ/SUPGO", "Governo\nSecretaria\nÀ SUPCONC, \nEfetuar os registros", "Despacho B"),
    )
    assert dados["despacho_demandante"] == {
        "ordem": 3, "nome": "Despacho B", "unidade": "SEFAZ/SUPGO", "criterio": "enderecado_a_nos",
        "data_assinatura": None,
    }
    assert dados["solicitante_demanda"] == "SEFAZ/SUPGO"
    assert dados["nivel_demanda"] == "INTERNA"


def test_aceita_endereco_com_vistas_acento_e_nome_antigo():
    dados = _calcular(_doc("SEFAZ/SUBAFIN", "À SUBTES, com vistas à Superintendência de Controles Financeiros"))
    assert dados["despacho_demandante"]["criterio"] == "enderecado_a_nos"
    assert dados["nivel_demanda"] == "SUPERIOR"


def test_documentos_da_nossa_unidade_nunca_sao_o_demandante():
    dados = _calcular(
        _doc("SEFAZ/SUPGO", "À SUPCONFI, efetuar registro", "Pedido"),
        _doc("SEFAZ/SUPCONFI", "À SUPGO, registro efetuado", "Resposta"),
    )
    assert dados["despacho_demandante"]["nome"] == "Pedido"
    assert [m["nome"] for m in dados["manifestacoes_nossas"]] == ["Resposta"]
    assert dados["manifestacoes_nossas"][0]["ordem"] == 2


def test_cai_para_documento_que_cita_nossa_unidade_e_depois_para_o_ultimo():
    citado = _calcular(
        _doc("SEFAZ/SUBTES", "Segue para providências da SUPCONC no mês"),
        _doc("SEFAZ/SUPGO", "Sem relação"),
    )
    assert citado["despacho_demandante"]["ordem"] == 1
    assert citado["despacho_demandante"]["criterio"] == "citado_no_texto"

    ultimo = _calcular(_doc("SEFAZ/SUBTES", "Nada"), _doc("SECC/CHEGAB", "Nada tambem"))
    assert ultimo["despacho_demandante"]["ordem"] == 2
    assert ultimo["despacho_demandante"]["criterio"] == "ultimo_de_outra_unidade"
    assert ultimo["nivel_demanda"] == "EXTERNA"


def test_sigla_parecida_nao_conta_como_nossa():
    dados = _calcular(_doc("SEFAZ/SUPCONT", "À SUPCONT, apenas"))
    assert dados["manifestacoes_nossas"] == []
    assert dados["despacho_demandante"]["criterio"] == "ultimo_de_outra_unidade"


def test_sem_documentos_ou_so_nossos_nao_ha_demandante():
    for docs in ([], [_doc("SEFAZ/SUPCONC", "À SUBTES")]):
        dados = _calcular(*docs)
        assert dados["despacho_demandante"] is None
        assert dados["solicitante_demanda"] is None
        assert dados["nivel_demanda"] is None


def test_linha_do_tempo_traz_todos_os_documentos_em_ordem():
    docs = [_doc("SEFAZ/A", nome=f"Doc {i}") for i in range(1, 21)]
    linha = _calcular(*docs)["linha_do_tempo"]
    assert [i["ordem"] for i in linha] == list(range(1, 21))
    assert (linha[0]["ordem"], linha[0]["nome"], linha[0]["unidade"]) == (1, "Doc 1", "SEFAZ/A")


def test_data_referencia_e_pre_calculado_entram_no_json():
    dados = preparar_para_automate(ProcessoSEI(numero="P", documentos=[_doc("SEFAZ/SUPGO", "À SUPCONC")]))
    assert dados["pre_calculado"]["data_referencia"] == datetime.fromisoformat(dados["gerado_em"]).strftime("%d/%m/%Y")
    assert dados["documentos"][0]["unidade"] == "SEFAZ/SUPHOB"  # SUPGO é o nome antigo da SUPHOB
    assert localizar_despacho_demandante([]) is None
