import logging
from pathlib import Path

import pytest
from jupiter import configurar_log

import config
import main


@pytest.fixture(autouse=True)
def teams_desligado(monkeypatch):
    """Nenhum teste pode mandar mensagem de verdade pelo Teams, mesmo que o .env tenha o webhook configurado."""
    monkeypatch.setattr(config, "TEAMS_WEBHOOK_URL", "")
    monkeypatch.setattr(config, "TEAMS_DESTINATARIOS", [])


@pytest.fixture(autouse=True)
def banco_so_de_teste(monkeypatch, tmp_path):
    """Nenhum teste lê nem grava o banco real (banco/agente.db), mesmo sem configurar um próprio."""
    monkeypatch.setattr(config, "CAMINHO_BANCO", tmp_path / "banco_de_teste.db")


@pytest.fixture(autouse=True, scope="session")
def log_dos_testes():
    """Um arquivo de log por rodada de testes, em logs/tests. A pasta logs/execução fica só com as execuções reais.

    Ao final, falha a sessão se algum log em arquivo tiver ido parar fora de logs/tests.
    """
    configurar_log("Testes", str(config.PASTA_LOGS_TESTES), str(config.PASTA_LOGS_TESTES_ERROS))
    logging.getLogger("jupiter").propagate = True  # o configurar_log desliga; o caplog do pytest precisa receber
    yield
    permitidas = {config.PASTA_LOGS_TESTES.resolve(), config.PASTA_LOGS_TESTES_ERROS.resolve()}
    fora = [
        h.baseFilename for h in logging.getLogger("jupiter").handlers
        if isinstance(h, logging.FileHandler) and Path(h.baseFilename).resolve().parent not in permitidas
    ]
    assert not fora, f"um teste gravou log fora de logs/tests: {fora}"


@pytest.fixture(autouse=True)
def log_do_agente_nao_e_religado(monkeypatch):
    """O main() reconfiguraria o log para logs/execução; nos testes vale o log de logs/tests."""
    monkeypatch.setattr(main, "_configurar_log", lambda: None)
