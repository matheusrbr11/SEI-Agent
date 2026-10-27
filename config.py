"""Configurações do SEI-Agent, carregadas do arquivo .env."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent

SEI_USUARIO = os.getenv("SEI_USUARIO", "").strip()
SEI_ORGAO = os.getenv("SEI_ORGAO", "SEFAZ").strip()
SEI_UNIDADE = os.getenv("SEI_UNIDADE", "SUPCONFI").strip()
SEI_MODO = os.getenv("SEI_MODO", "marcador").strip().lower()
SEI_MARCADOR = os.getenv("SEI_MARCADOR", "AGENTE - ANALISAR").strip()
LIMITE_TEXTO_DOCUMENTO = int(os.getenv("LIMITE_TEXTO_DOCUMENTO", "80"))
HEADLESS = os.getenv("HEADLESS", "False").strip().lower() == "true"

# Pasta do SharePoint sincronizada pelo OneDrive; vazio = não copia.
_pasta_sharepoint = os.getenv("SHAREPOINT_PASTA_ENTRADA", "").strip()
SHAREPOINT_PASTA_ENTRADA = Path(_pasta_sharepoint) if _pasta_sharepoint else None

# Pasta "saida" (análises geradas pelo Power Automate) sincronizada pelo OneDrive; vazio = não lê.
_pasta_saida = os.getenv("SHAREPOINT_PASTA_SAIDA", "").strip()
SHAREPOINT_PASTA_SAIDA = Path(_pasta_saida) if _pasta_saida else None
# Depois de entregar os JSONs, quanto esperar (no total) pelas análises do Power Automate, e de quanto em quanto tempo olhar.
SAIDA_ESPERA_MINUTOS = float(os.getenv("SAIDA_ESPERA_MINUTOS", "5"))
SAIDA_INTERVALO_SEGUNDOS = float(os.getenv("SAIDA_INTERVALO_SEGUNDOS", "20"))


def _emails(texto: str) -> list[str]:
    """E-mails separados por vírgula, sem espaços nem itens vazios."""
    return [e.strip() for e in texto.split(",") if e.strip()]


# Envio da análise corrigida a uma pessoa pelo Teams: webhook e e-mails (separados por vírgula) de quem a recebe.
# Sem webhook ou sem destinatários, nada é enviado.
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "").strip()
TEAMS_DESTINATARIOS = _emails(os.getenv("TEAMS_DESTINATARIOS", ""))
TEAMS_LIMITE_CARACTERES = int(os.getenv("TEAMS_LIMITE_CARACTERES", "25000"))  # o Teams recusa mensagens muito grandes

PASTA_DOWNLOADS = BASE_DIR / "downloads"
PASTA_LOGS = BASE_DIR / "logs" / "execução"  # só as execuções reais do agente
PASTA_LOGS_ERROS = PASTA_LOGS / "erros"
PASTA_LOGS_TESTES = BASE_DIR / "logs" / "tests"  # os testes gravam aqui, separados dos logs reais
PASTA_LOGS_TESTES_ERROS = PASTA_LOGS_TESTES / "erros"
PASTA_AUTOMATE = BASE_DIR / "automate"
PASTA_AUTOMATE_ENTRADA = PASTA_AUTOMATE / "entrada"
PASTA_AUTOMATE_SAIDA = PASTA_AUTOMATE / "saida"
PASTA_AUTOMATE_ERROS = PASTA_AUTOMATE / "erros"
CAMINHO_BANCO = BASE_DIR / "banco" / "agente.db"

for pasta in (
    PASTA_DOWNLOADS, PASTA_LOGS, PASTA_LOGS_ERROS,
    PASTA_AUTOMATE_ENTRADA, PASTA_AUTOMATE_SAIDA,
    PASTA_AUTOMATE_ERROS,
):
    pasta.mkdir(parents=True, exist_ok=True)

if SEI_MODO not in {"marcador", "novos"}:
    raise ValueError("SEI_MODO deve ser 'marcador' ou 'novos'.")
