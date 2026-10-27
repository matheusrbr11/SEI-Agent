"""SEI-Agent: coleta processos e os exporta para o SharePoint (pasta sincronizada)."""
from __future__ import annotations

import argparse
import getpass
import logging
import sys

import config
from jupiter import configurar_log
from automate import saidas, teams
from automate.exportador import copiar_para_sharepoint, exportar_para_automate
from banco.controle import ControleProcessos
from sei.sei_service import SEIService

configurar_log("Agente SEI", str(config.PASTA_LOGS), str(config.PASTA_LOGS_ERROS))
log = logging.getLogger("jupiter.agente.main")
if not any(isinstance(h, logging.StreamHandler) for h in log.handlers):
    log.addHandler(logging.StreamHandler(sys.stdout))


def argumentos():
    parser = argparse.ArgumentParser(description="Coleta processos do SEI para o Power Automate.")
    parser.add_argument("--processo", help="Processo único para teste.")
    parser.add_argument("--reanalisar", action="store_true", help="Exporta mesmo se já conhecido.")
    parser.add_argument("--sem-saida", action="store_true", help="Não espera nem processa as análises da pasta de saída.")
    return parser.parse_args()


def escolher_processos(sei, controle, processo_unico=None, reanalisar=False):
    todos = sei.listar_todos()  # também carrega metadados
    if processo_unico:
        return [processo_unico]
    if config.SEI_MODO == "marcador":
        candidatos = sei.listar_por_marcador(config.SEI_MARCADOR)
    else:
        if controle.vazio():
            controle.registrar_baseline(todos)
            log.info("Primeira execução: %d processos registrados como base.", len(todos))
            return []
        candidatos = todos
    return candidatos if reanalisar else [n for n in candidatos if not controle.conhecido(n)]


def entregar(arquivo) -> bool:
    """Copia o JSON para a pasta do SharePoint sincronizada, se configurada no .env. True se copiou."""
    if config.SHAREPOINT_PASTA_ENTRADA:
        destino = copiar_para_sharepoint(arquivo, config.SHAREPOINT_PASTA_ENTRADA)
        log.info("Entrada copiada para o SharePoint: %s", destino)
        return True
    return False


def _registrar(resultado):
    mensagem = (
        "Análise %s (processo %s): %d correção(ões), %d erro(s), %d aviso(s). Relatório: %s.validacao.txt"
        % (resultado.arquivo, resultado.numero or "?", len(resultado.correcoes), len(resultado.erros),
           len(resultado.avisos), resultado.arquivo.rsplit(".", 1)[0])
    )
    (log.error if resultado.erros else log.warning if resultado.avisos else log.info)(mensagem)
    for problema in resultado.problemas:
        log.info("    %s", problema)
    if teams.configurado():
        if teams.enviar_resultado(resultado):
            log.info("Análise %s enviada pelo Teams para %s.", resultado.arquivo, ", ".join(config.TEAMS_DESTINATARIOS))
        else:
            log.warning("Análise %s NÃO foi enviada pelo Teams (veja o log de erros).", resultado.arquivo)


def processar_saidas(entregues, antes):
    """Espera as análises NOVAS dos processos `entregues` na pasta de saída e corrige/valida as que chegarem.

    O que já estava na pasta (`antes`) e as análises de outros processos são ignorados.
    Nunca derruba a execução: erros e Ctrl+C só encerram a espera.
    """
    pasta = config.SHAREPOINT_PASTA_SAIDA
    if pasta is None or not entregues:
        return
    if not pasta.is_dir():
        log.warning("Pasta de saída não encontrada (OneDrive sincronizando?): %s", pasta)
        return
    log.info("Aguardando até %.0f min pelas análises de %d processo(s)...", config.SAIDA_ESPERA_MINUTOS, len(entregues))
    try:
        resultados, faltando = saidas.aguardar_e_processar(
            pasta, [config.PASTA_AUTOMATE_ENTRADA, config.SHAREPOINT_PASTA_ENTRADA], config.PASTA_AUTOMATE_SAIDA,
            entregues, antes, config.SAIDA_ESPERA_MINUTOS * 60, config.SAIDA_INTERVALO_SEGUNDOS, ao_processar=_registrar,
        )
    except KeyboardInterrupt:
        log.warning("Espera pelas análises interrompida.")
        return
    except Exception:
        log.exception("Falha ao processar a pasta de saída.")
        return
    if faltando:
        log.warning("Sem análise após %.0f min: %s. Rode `python -m automate.saidas` mais tarde.", config.SAIDA_ESPERA_MINUTOS, ", ".join(faltando))
    if resultados:
        log.info("Análises corrigidas em: %s", config.PASTA_AUTOMATE_SAIDA)


def main():
    args = argumentos()
    usuario = config.SEI_USUARIO or input("Usuário SEI: ").strip()
    senha = getpass.getpass("Senha SEI: ")
    antes = saidas.impressoes_existentes(config.SHAREPOINT_PASTA_SAIDA)  # o que já estava na saída antes desta execução
    entregues = []  # processos cujo JSON foi copiado para o SharePoint: as análises deles virão da pasta de saída
    sei = SEIService(config.PASTA_DOWNLOADS, config.LIMITE_TEXTO_DOCUMENTO, config.HEADLESS)
    controle = ControleProcessos(config.CAMINHO_BANCO)
    try:
        if not sei.autenticar(usuario, senha, config.SEI_ORGAO, config.SEI_UNIDADE):
            log.error("Não foi possível autenticar no SEI.")
            return 1
        del senha
        processos = escolher_processos(sei, controle, args.processo, args.reanalisar)
        log.info("%d processo(s) para exportar.", len(processos))
        for numero in processos:
            try:
                processo = sei.coletar_processo(numero)
                if processo is None:
                    controle.salvar(numero, "erro_coleta", erro="Falha na coleta")
                    continue
                arquivo = exportar_para_automate(processo, config.PASTA_AUTOMATE_ENTRADA)
                log.info("Entrada criada: %s", arquivo)
                try:
                    if entregar(arquivo):
                        entregues.append(numero)
                except Exception as erro:
                    log.error("Erro ao enviar %s: %s", numero, erro)
                    controle.salvar(numero, "erro_envio", arquivo_entrada=str(arquivo), erro=str(erro))
                    continue
                controle.salvar(numero, "exportado", arquivo_entrada=str(arquivo))
            except Exception as erro:
                log.exception("Erro ao processar %s", numero)
                controle.salvar(numero, "erro_coleta", erro=str(erro))
    finally:
        controle.fechar()
        sei.fechar()  # o navegador não precisa ficar aberto durante a espera pelas análises
    if not args.sem_saida:
        processar_saidas(entregues, antes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
