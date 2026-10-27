import logging
from pathlib import Path

import pytest

import config
import main


@pytest.fixture(autouse=True)
def lista_de_texto_modelo_limpa(monkeypatch):
    monkeypatch.setattr(config, "VARIAVEIS_COM_TEXTO_MODELO", [])


# --- texto

def test_texto_usa_o_padrao_quando_ausente_ou_vazio(monkeypatch):
    monkeypatch.delenv("X_TESTE", raising=False)
    assert config._texto("X_TESTE", "padrao") == "padrao"
    monkeypatch.setenv("X_TESTE", "   ")
    assert config._texto("X_TESTE", "padrao") == "padrao"


def test_texto_tira_espacos(monkeypatch):
    monkeypatch.setenv("X_TESTE", "  valor  ")
    assert config._texto("X_TESTE", "padrao") == "valor"


def test_texto_modelo_do_env_example_vale_o_padrao_e_fica_registrado(monkeypatch):
    monkeypatch.setenv("X_TESTE", "<seu usuário do SEI>")
    assert config._texto("X_TESTE", "padrao") == "padrao"
    assert config.VARIAVEIS_COM_TEXTO_MODELO == ["X_TESTE"]


def test_texto_comum_nao_e_registrado_como_modelo(monkeypatch):
    monkeypatch.setenv("X_TESTE", "AGENTE - ANALISAR")
    config._texto("X_TESTE")
    assert config.VARIAVEIS_COM_TEXTO_MODELO == []


# --- números

def test_numero_usa_o_padrao_e_o_tipo_pedido(monkeypatch):
    monkeypatch.delenv("X_NUM", raising=False)
    assert config._numero("X_NUM", 80, minimo=0, tipo=int) == 80 and isinstance(config._numero("X_NUM", 80, 0, int), int)
    assert config._numero("X_NUM", 5, minimo=0) == 5.0 and isinstance(config._numero("X_NUM", 5, 0), float)


def test_numero_le_o_valor_do_env(monkeypatch):
    monkeypatch.setenv("X_NUM", " 12 ")
    assert config._numero("X_NUM", 5, minimo=0, tipo=int) == 12


@pytest.mark.parametrize("valor", ["abc", "1,5", "12 min"])
def test_numero_invalido_diz_qual_variavel_esta_errada(monkeypatch, valor):
    monkeypatch.setenv("X_NUM", valor)
    with pytest.raises(ValueError, match=rf"X_NUM deve ser um número.*{valor!r}"):
        config._numero("X_NUM", 5, minimo=0, tipo=int)


def test_numero_abaixo_do_minimo_e_recusado(monkeypatch):
    monkeypatch.setenv("X_NUM", "0")
    with pytest.raises(ValueError, match="X_NUM deve ser no mínimo 1"):
        config._numero("X_NUM", 20, minimo=1)


def test_numero_com_texto_modelo_vale_o_padrao(monkeypatch):
    monkeypatch.setenv("X_NUM", "<segundos>")
    assert config._numero("X_NUM", 20, minimo=1) == 20.0


# --- booleano

@pytest.mark.parametrize("valor, esperado", [("True", True), ("true", True), ("1", True), ("sim", True),
                                              ("False", False), ("0", False), ("não", False), ("nao", False)])
def test_booleano(monkeypatch, valor, esperado):
    monkeypatch.setenv("X_BOOL", valor)
    assert config._booleano("X_BOOL", not esperado) is esperado


def test_booleano_ausente_usa_o_padrao(monkeypatch):
    monkeypatch.delenv("X_BOOL", raising=False)
    assert config._booleano("X_BOOL", True) is True


def test_booleano_invalido_nao_vira_falso_em_silencio(monkeypatch):
    monkeypatch.setenv("X_BOOL", "talvez")
    with pytest.raises(ValueError, match="X_BOOL deve ser True ou False.*'talvez'"):
        config._booleano("X_BOOL", False)


# --- escolha e pasta

def test_escolha_aceita_maiusculas_e_recusa_valor_desconhecido(monkeypatch):
    monkeypatch.setenv("X_MODO", " Novos ")
    assert config._escolha("X_MODO", "marcador", {"marcador", "novos"}) == "novos"
    monkeypatch.setenv("X_MODO", "todos")
    with pytest.raises(ValueError, match="X_MODO deve ser 'marcador' ou 'novos'.*'todos'"):
        config._escolha("X_MODO", "marcador", {"marcador", "novos"})


def test_pasta_vazia_ou_com_texto_modelo_nao_e_usada(monkeypatch):
    monkeypatch.setenv("X_PASTA", "")
    assert config._pasta("X_PASTA") is None
    monkeypatch.setenv("X_PASTA", "<caminho da pasta de entrada do SharePoint, sincronizada pelo OneDrive>")
    assert config._pasta("X_PASTA") is None
    assert config.VARIAVEIS_COM_TEXTO_MODELO == ["X_PASTA"]


def test_pasta_preenchida_vira_path(monkeypatch):
    monkeypatch.setenv("X_PASTA", "C:/um/caminho")
    assert config._pasta("X_PASTA") == Path("C:/um/caminho")


# --- aviso no main

def test_main_avisa_quais_variaveis_estao_com_texto_modelo(monkeypatch, caplog):
    monkeypatch.setattr(config, "VARIAVEIS_COM_TEXTO_MODELO", ["SEI_USUARIO", "SHAREPOINT_PASTA_SAIDA"])
    with caplog.at_level(logging.WARNING):
        main._avisar_texto_modelo()
    assert "SEI_USUARIO, SHAREPOINT_PASTA_SAIDA" in caplog.text


def test_main_nao_avisa_quando_nao_ha_texto_modelo(caplog):
    with caplog.at_level(logging.WARNING):
        main._avisar_texto_modelo()
    assert caplog.text == ""
