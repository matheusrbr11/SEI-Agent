"""O prompt.md é a cópia de referência do prompt do Power Automate: tem de continuar de acordo com o validador.

Se um destes testes falhar, o prompt e o validador se afastaram: ou o prompt mudou e o `automate/validador.py`
(e o `correcao.py`) precisa acompanhar, ou o contrário. Sem isso o validador passa a dar ERRO em análises corretas.
"""
import re
from pathlib import Path

import pytest

from automate import validador

PROMPT = (Path(__file__).resolve().parent.parent / "prompt.md").read_text(encoding="utf-8")


def _posicao_do_titulo(nivel: str, titulo: str) -> int:
    achado = re.search(rf"^{nivel} {re.escape(titulo)}\s*$", PROMPT, re.M)
    return achado.start() if achado else -1


@pytest.mark.parametrize("secao", validador.SECOES)
def test_prompt_tem_cada_secao_que_o_validador_exige(secao):
    assert _posicao_do_titulo("##", secao) >= 0, f"o prompt.md não tem o título '## {secao}'"


def test_prompt_tem_as_secoes_na_ordem_que_o_validador_exige():
    posicoes = [_posicao_do_titulo("##", secao) for secao in validador.SECOES]
    assert posicoes == sorted(posicoes), "as seções do prompt.md estão fora da ordem de validador.SECOES"


@pytest.mark.parametrize("subsecao", ["Roteiro", "Despacho"])
def test_prompt_tem_as_subsecoes_da_proposta(subsecao):
    assert _posicao_do_titulo("###", subsecao) >= 0, f"o prompt.md não tem o título '### {subsecao}'"


@pytest.mark.parametrize("valor", validador.TIPOS_DE_PROVIDENCIA)
def test_prompt_cita_cada_tipo_de_providencia(valor):
    assert valor in PROMPT, f"o prompt.md não cita o tipo de providência '{valor}'"


@pytest.mark.parametrize("valor", validador.COMPETENCIAS)
def test_prompt_cita_cada_competencia(valor):
    assert valor in PROMPT, f"o prompt.md não cita a competência '{valor}'"


@pytest.mark.parametrize("valor", validador.SITUACOES)
def test_prompt_cita_cada_situacao_de_resposta(valor):
    assert valor in PROMPT, f"o prompt.md não cita a situação de resposta '{valor}'"
