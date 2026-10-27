import argparse

import pytest

import config
import main
from sei import credenciais

SERVICO = credenciais.SERVICO


def test_guardar_obter_e_apagar(cofre):
    assert credenciais.obter("fulano") is None
    credenciais.guardar("fulano", "segredo")
    assert credenciais.obter("fulano") == "segredo" and cofre == {(SERVICO, "fulano"): "segredo"}
    assert credenciais.apagar("fulano") is True and credenciais.obter("fulano") is None
    assert credenciais.apagar("fulano") is False


def test_cofre_com_defeito_vira_none_e_nao_levanta(monkeypatch):
    def quebrado(*args):
        raise credenciais.KeyringError("cofre indisponível")

    monkeypatch.setattr(credenciais.keyring, "get_password", quebrado)
    assert credenciais.obter("fulano") is None


# --- linha de comando

@pytest.fixture
def usuario(monkeypatch):
    monkeypatch.setattr(config, "SEI_USUARIO", "fulano")


def _senhas(monkeypatch, *digitadas):
    pendentes = list(digitadas)
    monkeypatch.setattr(credenciais.getpass, "getpass", lambda *_: pendentes.pop(0))


def test_cadastrar_guarda_a_senha_sem_mostra_la(usuario, cofre, monkeypatch, capsys):
    _senhas(monkeypatch, "s3nh@", "s3nh@")
    assert credenciais.main(["x", "--cadastrar"]) == 0
    assert cofre == {(SERVICO, "fulano"): "s3nh@"}
    assert "s3nh@" not in capsys.readouterr().out


@pytest.mark.parametrize("digitadas", [("abc", "abd"), ("", "")])
def test_cadastrar_recusa_senha_vazia_ou_diferente_da_repeticao(usuario, cofre, monkeypatch, digitadas):
    _senhas(monkeypatch, *digitadas)
    assert credenciais.main(["x", "--cadastrar"]) == 1
    assert cofre == {}


def test_verificar_e_apagar(usuario, cofre, monkeypatch, capsys):
    assert credenciais.main(["x", "--verificar"]) == 1 and "NÃO guardada" in capsys.readouterr().out
    credenciais.guardar("fulano", "segredo")
    assert credenciais.main(["x", "--verificar"]) == 0
    saida = capsys.readouterr().out
    assert "guardada" in saida and "segredo" not in saida
    assert credenciais.main(["x", "--apagar"]) == 0 and cofre == {}


def test_sem_opcao_mostra_o_uso(capsys):
    assert credenciais.main(["x"]) == 2 and "--cadastrar" in capsys.readouterr().out


# --- como o main() obtém usuário e senha

def test_main_usa_a_senha_do_cofre_sem_perguntar(usuario, monkeypatch):
    credenciais.guardar("fulano", "do-cofre")
    monkeypatch.setattr(main, "_interativo", lambda: False)
    assert main.obter_credenciais() == ("fulano", "do-cofre")


def test_main_pergunta_a_senha_quando_o_cofre_esta_vazio_e_ha_alguem_no_terminal(usuario, monkeypatch):
    monkeypatch.setattr(main, "_interativo", lambda: True)
    monkeypatch.setattr(main.getpass, "getpass", lambda *_: "digitada")
    assert main.obter_credenciais() == ("fulano", "digitada")


def test_sem_senha_e_sem_terminal_nao_trava_esperando_e_diz_como_cadastrar(usuario, monkeypatch, caplog):
    monkeypatch.setattr(main, "_interativo", lambda: False)
    monkeypatch.setattr(main.log, "propagate", True)
    monkeypatch.setattr(main.getpass, "getpass", lambda *_: pytest.fail("não pode pedir senha sem terminal"))
    assert main.obter_credenciais() is None
    assert "python -m sei.credenciais --cadastrar" in caplog.text


def test_sem_usuario_e_sem_terminal_nao_trava(monkeypatch):
    monkeypatch.setattr(config, "SEI_USUARIO", "")
    monkeypatch.setattr(main, "_interativo", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("não pode perguntar sem terminal"))
    assert main.obter_credenciais() is None


def test_main_devolve_1_sem_credencial(monkeypatch):
    monkeypatch.setattr(main, "argumentos", lambda: argparse.Namespace(processo=None, reanalisar=False, sem_saida=True))
    monkeypatch.setattr(main, "obter_credenciais", lambda: None)
    monkeypatch.setattr(main, "SEIService", lambda *a, **k: pytest.fail("não deve abrir o navegador sem credencial"))
    assert main.main() == 1
