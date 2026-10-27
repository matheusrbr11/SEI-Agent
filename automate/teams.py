"""Envia a análise corrigida a uma pessoa pelo Teams, por um webhook.

O webhook recebe o JSON no formato de `GraphAPI.enviar_mensagem` da jupiter: {"destinatarios": [...], "mensagem": "..."}.
Ele não aceita anexo, então a análise vai como texto da mensagem.

Uso (para testar a configuração do .env, sem precisar de uma análise):
    python -m automate.teams --teste
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path

import requests

logger = logging.getLogger("jupiter.agente.teams")

TIMEOUT_SEGUNDOS = 30
PAUSAS_ENTRE_TENTATIVAS = (5, 15)  # segundos antes da 2ª e da 3ª tentativa
_CHAVE_NA_URL = re.compile(r"sig=[^&\s'\")]+")
_ABERTURA = "SEI-Agent\n\n---\n"  # cabeçalho em texto simples; veja o docstring de montar_mensagem


def montar_mensagem(markdown: str, limite: int) -> str:
    """O texto da análise (Markdown) depois de um cabeçalho mínimo; sem rodapé. Acima do limite do Teams, é cortado e o
    corte vai para o log.

    O cabeçalho ("SEI-Agent", uma linha em branco e "---") existe porque, sem ele, o "## Processo" aparecia como texto cru
    no Teams. Observado: a formatação só funciona com a linha "---" antes do primeiro título, e o cabeçalho precisa ser
    texto simples: com "#" ou negrito ("**") no início, tudo ficava como texto cru.
    """
    texto = markdown.strip()
    if len(texto) > limite - len(_ABERTURA):
        logger.warning("Análise com %d caracteres cortada em %d para caber no Teams.", len(texto), limite)
        texto = texto[: limite - len(_ABERTURA)].rstrip()
    return _ABERTURA + texto


def _ocultar_chave(texto: str) -> str:
    """O webhook leva a chave de acesso na URL (`sig=`) e as exceções do `requests` repetem a URL inteira."""
    return _CHAVE_NA_URL.sub("sig=***", texto)


def _passageira(erro: requests.exceptions.RequestException) -> bool:
    """Vale tentar de novo: falha de rede/SSL, tempo esgotado, servidor com problema ou limite de uso (429)."""
    resposta = getattr(erro, "response", None)
    if resposta is not None:
        return resposta.status_code >= 500 or resposta.status_code == 429
    return isinstance(erro, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


def enviar(mensagem: str, webhook_url: str, destinatarios: list[str]) -> bool:
    """POST no webhook do Teams, com até 3 tentativas nas falhas passageiras. Devolve False (e registra no log, sem a chave
    do webhook) se não conseguir; nunca levanta exceção."""
    tentativas = len(PAUSAS_ENTRE_TENTATIVAS) + 1
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = requests.post(
                webhook_url, json={"destinatarios": destinatarios, "mensagem": mensagem}, timeout=TIMEOUT_SEGUNDOS
            )
            resposta.raise_for_status()
        except requests.exceptions.RequestException as erro:
            motivo = _ocultar_chave(f"{type(erro).__name__}: {erro}")
            if tentativa < tentativas and _passageira(erro):
                pausa = PAUSAS_ENTRE_TENTATIVAS[tentativa - 1]
                logger.warning("Envio ao Teams falhou (tentativa %d de %d), nova tentativa em %ds: %s", tentativa, tentativas, pausa, motivo)
                time.sleep(pausa)
                continue
            logger.error("Erro ao enviar a mensagem ao Teams (tentativa %d de %d): %s", tentativa, tentativas, motivo)
            return False
        logger.info("Mensagem enviada ao Teams para %s. Status: %s", ", ".join(destinatarios), resposta.status_code)
        return True
    return False


def configurado() -> bool:
    import config

    return bool(config.TEAMS_WEBHOOK_URL and config.TEAMS_DESTINATARIOS)


def enviar_resultado(resultado) -> bool:
    """Envia a análise corrigida (já gravada em `resultado.corrigido`) às pessoas configuradas. False se não enviou."""
    import config

    if not configurado() or not resultado.corrigido:
        return False
    try:
        caminho = Path(resultado.corrigido)
        markdown = caminho.read_text(encoding="utf-8")
    except OSError:
        logger.error("Não foi possível ler a análise corrigida para enviar ao Teams: %s", resultado.corrigido, exc_info=True)
        return False
    return enviar(montar_mensagem(markdown, config.TEAMS_LIMITE_CARACTERES), config.TEAMS_WEBHOOK_URL, config.TEAMS_DESTINATARIOS)


def main(argv: list[str]) -> int:
    import config

    if argv[1:] != ["--teste"]:
        print(__doc__)
        return 2
    if not config.TEAMS_WEBHOOK_URL:
        print("Sem webhook: preencha TEAMS_WEBHOOK_URL no .env.")
        return 2
    if not config.TEAMS_DESTINATARIOS:
        print("Sem destinatário: preencha TEAMS_DESTINATARIOS no .env (e-mails separados por vírgula).")
        return 2
    ok = enviar(
        "Teste do SEI-Agent: se você recebeu esta mensagem, o envio das análises pelo Teams está configurado.",
        config.TEAMS_WEBHOOK_URL, config.TEAMS_DESTINATARIOS,
    )
    print(f"Mensagem de teste enviada para: {', '.join(config.TEAMS_DESTINATARIOS)}" if ok else "Falha ao enviar (veja o log).")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
