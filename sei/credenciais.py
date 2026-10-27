"""Senha do SEI guardada no Gerenciador de Credenciais do Windows (via `keyring`), para o agente rodar sem ninguém digitar.

A senha fica criptografada pelo Windows, ligada ao usuário do Windows que a cadastrou: só esse usuário a lê, e por isso o
Agendador de Tarefas precisa rodar com o mesmo usuário. Ela nunca vai para o `.env`, o banco ou os logs.

Uso:
    python -m sei.credenciais --cadastrar   # pede a senha e guarda (também serve para trocá-la)
    python -m sei.credenciais --verificar   # diz se há senha guardada, sem mostrá-la
    python -m sei.credenciais --apagar
O usuário vem de SEI_USUARIO, no .env (ou é perguntado).
"""
from __future__ import annotations

import getpass
import logging
import sys

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

logger = logging.getLogger("jupiter.agente.credenciais")

SERVICO = "SEI-Agent"


def obter(usuario: str) -> str | None:
    """A senha guardada para o usuário, ou None se não houver (ou se o Windows não a entregar; o motivo vai ao log)."""
    try:
        return keyring.get_password(SERVICO, usuario) or None
    except KeyringError:
        logger.warning("Não foi possível ler a senha do Gerenciador de Credenciais.", exc_info=True)
        return None


def guardar(usuario: str, senha: str) -> None:
    keyring.set_password(SERVICO, usuario, senha)


def apagar(usuario: str) -> bool:
    """False se não havia senha guardada."""
    try:
        keyring.delete_password(SERVICO, usuario)
    except PasswordDeleteError:
        return False
    return True


def _usuario() -> str:
    import config

    return config.SEI_USUARIO or input("Usuário SEI: ").strip()


def main(argv: list[str]) -> int:
    opcoes = argv[1:]
    if len(opcoes) != 1 or opcoes[0] not in ("--cadastrar", "--verificar", "--apagar"):
        print(__doc__)
        return 2
    usuario = _usuario()
    if not usuario:
        print("Informe o usuário do SEI (SEI_USUARIO no .env).")
        return 2
    try:
        if opcoes[0] == "--verificar":
            existe = obter(usuario) is not None
            print(f"Senha de '{usuario}' {'guardada' if existe else 'NÃO guardada'} no Gerenciador de Credenciais (serviço '{SERVICO}').")
            return 0 if existe else 1
        if opcoes[0] == "--apagar":
            print("Senha apagada." if apagar(usuario) else "Não havia senha guardada.")
            return 0
        senha = getpass.getpass(f"Senha do SEI para '{usuario}': ")
        if not senha or senha != getpass.getpass("Repita a senha: "):
            print("Senha vazia ou diferente da repetição: nada foi guardado.")
            return 1
        guardar(usuario, senha)
    except KeyringError as erro:
        print(f"O Gerenciador de Credenciais do Windows recusou a operação: {erro}")
        return 1
    print(f"Senha de '{usuario}' guardada. A senha não é testada aqui: o próximo login no SEI mostra se ela está certa.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
