import pytest

import config


@pytest.fixture(autouse=True)
def teams_desligado(monkeypatch):
    """Nenhum teste pode mandar mensagem de verdade pelo Teams, mesmo que o .env tenha o webhook configurado."""
    monkeypatch.setattr(config, "TEAMS_WEBHOOK_URL", "")
    monkeypatch.setattr(config, "TEAMS_DESTINATARIOS", [])
