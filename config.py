"""Configurações do SEI-Agent, carregadas do arquivo .env."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent

# Variáveis do .env que ainda têm o texto-modelo do .env.example ("<seu usuário do SEI>"): são ignoradas, como se
# estivessem vazias. O main.py avisa quais são no log.
VARIAVEIS_COM_TEXTO_MODELO: list[str] = []


def _texto(nome: str, padrao: str = "") -> str:
    """Valor da variável, sem espaços; vazio ou com o texto-modelo do .env.example ("<...>") vale o padrão."""
    valor = os.getenv(nome, "").strip()
    if valor.startswith("<"):
        VARIAVEIS_COM_TEXTO_MODELO.append(nome)
        return padrao
    return valor or padrao


def _numero(nome: str, padrao, minimo, tipo=float):
    """Número lido da variável; o erro diz qual variável está errada, em vez de um ValueError genérico."""
    texto = _texto(nome, str(padrao))
    try:
        valor = tipo(texto)
    except ValueError:
        raise ValueError(f"{nome} deve ser um número, mas no .env está {texto!r}.") from None
    if valor < minimo:
        raise ValueError(f"{nome} deve ser no mínimo {minimo}, mas no .env está {texto!r}.")
    return valor


def _booleano(nome: str, padrao: bool) -> bool:
    texto = _texto(nome, str(padrao)).lower()
    if texto in {"true", "1", "sim", "yes"}:
        return True
    if texto in {"false", "0", "nao", "não", "no"}:
        return False
    raise ValueError(f"{nome} deve ser True ou False, mas no .env está {texto!r}.")


def _escolha(nome: str, padrao: str, validas: set[str]) -> str:
    texto = _texto(nome, padrao).lower()
    if texto not in validas:
        raise ValueError(f"{nome} deve ser {' ou '.join(repr(v) for v in sorted(validas))}, mas no .env está {texto!r}.")
    return texto


def _pasta(nome: str) -> Path | None:
    """Pasta do SharePoint sincronizada pelo OneDrive; vazio = não usa."""
    texto = _texto(nome)
    return Path(texto) if texto else None


def _emails(texto: str) -> list[str]:
    """E-mails separados por vírgula, sem espaços nem itens vazios."""
    return [e.strip() for e in texto.split(",") if e.strip()]


SEI_USUARIO = _texto("SEI_USUARIO")
SEI_ORGAO = _texto("SEI_ORGAO", "SEFAZ")
SEI_UNIDADE = _texto("SEI_UNIDADE", "SUPCONFI")
SEI_MODO = _escolha("SEI_MODO", "marcador", {"marcador", "novos"})
SEI_MARCADOR = _texto("SEI_MARCADOR", "AGENTE - ANALISAR")
LIMITE_TEXTO_DOCUMENTO = _numero("LIMITE_TEXTO_DOCUMENTO", 80, minimo=0, tipo=int)
HEADLESS = _booleano("HEADLESS", False)
# Quantas vezes seguidas um processo pode falhar (coleta ou entrega) antes de o agente parar de tentá-lo sozinho.
TENTATIVAS_MAXIMAS = _numero("TENTATIVAS_MAXIMAS", 3, minimo=1, tipo=int)

# Pasta "entrada" do SharePoint (o agente copia os JSONs para lá); vazio = não copia.
SHAREPOINT_PASTA_ENTRADA = _pasta("SHAREPOINT_PASTA_ENTRADA")
# Pasta "saida" (análises geradas pelo Power Automate); vazio = não lê.
SHAREPOINT_PASTA_SAIDA = _pasta("SHAREPOINT_PASTA_SAIDA")
# Depois de entregar os JSONs, quanto esperar (no total) pelas análises do Power Automate, e de quanto em quanto tempo olhar.
SAIDA_ESPERA_MINUTOS = _numero("SAIDA_ESPERA_MINUTOS", 5, minimo=0)
SAIDA_INTERVALO_SEGUNDOS = _numero("SAIDA_INTERVALO_SEGUNDOS", 20, minimo=1)

# Envio da análise corrigida a uma pessoa pelo Teams: webhook e e-mails (separados por vírgula) de quem a recebe.
# Sem webhook ou sem destinatários, nada é enviado.
TEAMS_WEBHOOK_URL = _texto("TEAMS_WEBHOOK_URL")
TEAMS_DESTINATARIOS = _emails(_texto("TEAMS_DESTINATARIOS"))
TEAMS_LIMITE_CARACTERES = _numero("TEAMS_LIMITE_CARACTERES", 25000, minimo=100, tipo=int)  # o Teams recusa mensagens grandes

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
