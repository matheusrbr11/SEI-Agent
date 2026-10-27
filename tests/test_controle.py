import pytest
from banco.controle import ControleProcessos


@pytest.fixture
def controle(tmp_path):
    c = ControleProcessos(tmp_path / "teste.db")
    yield c
    c.fechar()


def test_banco_novo_esta_vazio(controle):
    assert controle.vazio()


def test_salvar_e_conhecido(controle):
    controle.salvar("P1", "exportado", arquivo_entrada="a.json")
    assert not controle.vazio()
    assert controle.conhecido("P1")
    assert not controle.conhecido("P2")


def test_erros_nao_sao_conhecidos(controle):
    controle.salvar("P1", "erro_coleta", erro="falha")
    controle.salvar("P2", "erro_ia", erro="falha")
    assert not controle.conhecido("P1")
    assert not controle.conhecido("P2")


def test_status_invalido(controle):
    with pytest.raises(ValueError):
        controle.salvar("P1", "qualquer")


def test_upsert_preserva_arquivos_e_limpa_erro(controle):
    controle.salvar("P1", "exportado", arquivo_entrada="a.json")
    controle.salvar("P1", "analisado", arquivo_saida="a.md")
    linha = controle.conexao.execute(
        "SELECT status, arquivo_entrada, arquivo_saida, erro FROM processos WHERE numero='P1'"
    ).fetchone()
    assert linha == ("analisado", "a.json", "a.md", None)
    assert controle.conexao.execute("SELECT COUNT(*) FROM processos").fetchone()[0] == 1


def test_registrar_baseline(controle):
    controle.registrar_baseline(["P1", "P2", "P3"])
    assert all(controle.conhecido(n) for n in ("P1", "P2", "P3"))
