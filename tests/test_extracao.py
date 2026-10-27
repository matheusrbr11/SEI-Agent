from datetime import date

import pytest

from automate.extracao import (
    data_assinatura,
    destinatarios,
    prazos_no_texto,
    usar_nome_atual,
    usar_nome_atual_em,
)


def test_data_assinatura_le_a_linha_de_assinatura_do_sei():
    texto = (
        "Atenciosamente,\n"
        "Documento assinado eletronicamente por Fulano de Tal, Superintendente, em 04/08/2026, às 17:08, "
        "conforme horário oficial de Brasília, com fundamento nos art. 28º e 29º do Decreto nº 48.209, "
        "de 19 de setembro de 2022.\n"
        "Criado por fulano, versão 2 por fulano em 09/09/2026 18:46:01."
    )
    assert data_assinatura(texto) == date(2026, 8, 4)  # "Criado por ... em" não é assinatura


def test_data_assinatura_com_varios_signatarios_usa_a_mais_recente():
    texto = (
        "Documento assinado eletronicamente por A, Chefe, em 04/08/2026, às 17:08, "
        "e por B, Superintendente, em 06/08/2026, às 09:55, conforme horário oficial."
    )
    assert data_assinatura(texto) == date(2026, 8, 6)


@pytest.mark.parametrize("texto", [None, "", "Sem assinatura nenhuma, em 04/08/2026, às 17:08"])
def test_data_assinatura_ausente(texto):
    assert data_assinatura(texto) is None


def test_destinatarios_copia_as_linhas_de_enderecamento_na_grafia_da_fonte():
    texto = (
        "Governo do Estado do Rio de Janeiro\n"
        "Secretaria de Estado de Fazenda\n"
        "À Subsecretaria de Controle Interno - SUBCINT,\n"
        "cumprimentando-os cordialmente, encaminho o presente processo.\n"
        "À Subsecretaria do Tesouro Estadual - SUBTES,\n"
        "Com vistas à SEFAZ/SUPCONC:\n"
        "Com cópia para a CHEFIA DE GABINETE, para ciência,\n"
    )
    assert destinatarios(texto) == [
        "À Subsecretaria de Controle Interno - SUBCINT",
        "À Subsecretaria do Tesouro Estadual - SUBTES",
        "Com vistas à SEFAZ/SUPCONC",
    ]


def test_destinatarios_de_oficio_com_marcador_sozinho_na_linha():
    texto = "Of. Nº42 Rio de Janeiro, 04 de agosto de 2026\nAo\nBanco Itaú.\nAv. Nilo Peçanha, 50\nPrezados Senhores,"
    assert destinatarios(texto) == ["Ao Banco Itaú"]


def test_destinatarios_ignora_frases_longas_e_texto_vazio():
    longa = "Ao analisar o presente processo, verificamos que " + "x" * 200
    assert destinatarios(longa) == []
    assert destinatarios(None) == []


def test_prazos_acha_datas_com_ano_de_2_ou_4_digitos_sem_repetir():
    texto = (
        "PRAZO : 29/07/2026\n"
        "Considerando que o prazo fixado encerra-se em 29/07/2026, observado o prazo final de até 06/08/26 "
        "(137821655)."
    )
    assert [data for data, _ in prazos_no_texto(texto)] == [date(2026, 7, 29), date(2026, 8, 6)]


def test_prazos_so_conta_datas_perto_de_palavras_de_prazo():
    texto = "O processo foi recebido em 28/07/2026. Rio de Janeiro, 04/08/2026."
    assert prazos_no_texto(texto) == []


def test_prazos_ignora_numero_de_processo_e_data_invalida():
    texto = "O prazo do processo SEI-040005/000729/2026 vence em 31/02/2026 ou até o dia 06/08/2026."
    assert [data for data, _ in prazos_no_texto(texto)] == [date(2026, 8, 6)]


def test_prazos_traz_trecho_com_o_contexto():
    (data, trecho), = prazos_no_texto("Confirmo a prorrogação do prazo até o dia 06/08/2026.")
    assert "prorrogação do prazo" in trecho and "06/08/2026" in trecho


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("À SUPCONC,", "À SUPCONFI,"),
        ("SEFAZ/SUPCONC", "SEFAZ/SUPCONFI"),
        ("SUPCONC/SUPCONFI", "SUPCONFI"),
        ("SUPCONFI (SUPCONC)", "SUPCONFI"),
        ("Superintendente SUPCONC.", "Superintendente SUPCONFI."),
        ("Cc SUPCONC SUBTES <supconc.subtes@fazenda.rj.gov.br>", "Cc SUPCONFI SUBTES <supconc.subtes@fazenda.rj.gov.br>"),
        ("SUPCONC.SUBTES@FAZENDA.RJ.GOV.BR", "SUPCONC.SUBTES@FAZENDA.RJ.GOV.BR"),
        ("SUPCONT", "SUPCONT"),
        ("supconc", "supconc"),
    ],
)
def test_usar_nome_atual(entrada, esperado):
    assert usar_nome_atual(entrada) == esperado


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("À SEFAZ/SUPGO,", "À SEFAZ/SUPHOB,"),
        ("SEFAZ/SUPAEF", "SEFAZ/SUPADFIN"),
        ("SUPGO/SUPHOB", "SUPHOB"),
        ("SUPADFIN (SUPAEF)", "SUPADFIN"),
        ("SUPGO, SUPAEF e SUPCONC", "SUPHOB, SUPADFIN e SUPCONFI"),
        ("supgo@fazenda.rj.gov.br e SUPGO.X@FAZENDA.RJ.GOV.BR", "supgo@fazenda.rj.gov.br e SUPGO.X@FAZENDA.RJ.GOV.BR"),
        ("SUPGOV e SUPAEFX", "SUPGOV e SUPAEFX"),  # só a sigla inteira
    ],
)
def test_usar_nome_atual_com_os_tres_nomes(entrada, esperado):
    assert usar_nome_atual(entrada) == esperado


def test_nomes_de_documentos_ficam_como_na_fonte():
    texto = "Ofício SUPGO nº 5 foi enviado à SUPGO."
    assert usar_nome_atual(texto, protegidos={"Ofício SUPGO nº 5"}) == "Ofício SUPGO nº 5 foi enviado à SUPHOB."
    dados = {"nome": "Ofício SUPGO nº 5", "unidade": "SEFAZ/SUPGO", "lista": ["Ofício SUPGO nº 5 - SUPAEF"]}
    assert usar_nome_atual_em(dados, protegidos={"Ofício SUPGO nº 5"}) == {
        "nome": "Ofício SUPGO nº 5",
        "unidade": "SEFAZ/SUPHOB",
        "lista": ["Ofício SUPGO nº 5 - SUPADFIN"],
    }


def test_usar_nome_atual_em_estrutura_aninhada():
    dados = {"a": ["SEFAZ/SUPCONC", {"b": "À SUPCONC"}], "n": 3, "v": None}
    assert usar_nome_atual_em(dados) == {"a": ["SEFAZ/SUPCONFI", {"b": "À SUPCONFI"}], "n": 3, "v": None}
