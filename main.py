"""SEI-Agent: coleta processos e os exporta para o SharePoint (pasta sincronizada)."""
from __future__ import annotations

import argparse
import getpass
import logging
import sys
from datetime import datetime
from pathlib import Path

import config
from jupiter import configurar_log
from automate import saidas, teams
from automate.exportador import copiar_para_sharepoint, exportar_para_automate
from banco.controle import ControleProcessos
from sei import credenciais
from sei.sei_service import SEIService

log = logging.getLogger("jupiter.agente.main")


def _configurar_log() -> None:
    """Liga o log em arquivo e na tela. Só roda na execução do agente, e não ao importar o módulo (os testes importam)."""
    configurar_log("Agente SEI", str(config.PASTA_LOGS), str(config.PASTA_LOGS_ERROS))
    if not any(isinstance(h, logging.StreamHandler) for h in log.handlers):
        log.addHandler(logging.StreamHandler(sys.stdout))


def _avisar_texto_modelo() -> None:
    """Avisa quais variáveis do .env ainda têm o texto-modelo do .env.example (o agente as trata como não preenchidas)."""
    if config.VARIAVEIS_COM_TEXTO_MODELO:
        log.warning(
            "Variáveis do .env ainda com o texto-modelo do .env.example (ignoradas): %s",
            ", ".join(config.VARIAVEIS_COM_TEXTO_MODELO),
        )


def _interativo() -> bool:
    """Há alguém no terminal para digitar? No Agendador de Tarefas, não."""
    return sys.stdin is not None and sys.stdin.isatty()


def obter_credenciais() -> tuple[str, str] | None:
    """(usuário, senha) do SEI. A senha vem do Gerenciador de Credenciais do Windows; sem ela, e só com alguém no terminal,
    é perguntada. Devolve None (com o motivo no log) se faltar algum dos dois e não houver quem digite."""
    usuario = config.SEI_USUARIO or (input("Usuário SEI: ").strip() if _interativo() else "")
    if not usuario:
        log.error("Sem usuário do SEI: preencha SEI_USUARIO no .env.")
        return None
    senha = credenciais.obter(usuario)
    if senha:
        log.info("Senha do SEI lida do Gerenciador de Credenciais.")
        return usuario, senha
    if not _interativo():
        log.error("Sem senha do SEI guardada para '%s' e ninguém no terminal para digitá-la. Cadastre com: python -m sei.credenciais --cadastrar", usuario)
        return None
    return usuario, getpass.getpass("Senha SEI: ")


def argumentos():
    parser = argparse.ArgumentParser(description="Coleta processos do SEI para o Power Automate.")
    parser.add_argument("--processo", help="Processo único para teste.")
    parser.add_argument("--reanalisar", action="store_true", help="Exporta mesmo se já conhecido.")
    parser.add_argument("--sem-saida", action="store_true", help="Não espera nem processa as análises da pasta de saída.")
    return parser.parse_args()


def escolher_processos(sei, controle, processo_unico=None, reanalisar=False, tentativas_maximas=None):
    """Processos a exportar. `--processo` e `--reanalisar` ignoram o banco; sem eles, `tentativas_maximas` (se vier)
    deixa de lado os que já falharam esse tanto de vezes seguidas."""
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
    if reanalisar:
        return candidatos
    novos = [n for n in candidatos if not controle.conhecido(n)]
    if tentativas_maximas is None:
        return novos
    escolhidos = []
    for numero in novos:
        if controle.desistiu(numero, tentativas_maximas):
            log.warning(
                "%s ignorado: falhou %d vezes seguidas. Use `--processo` para tentar de novo.", numero, tentativas_maximas
            )
            controle.registrar_evento(numero, "desistiu", "aviso", f"{tentativas_maximas} falhas seguidas")
        else:
            escolhidos.append(numero)
    return escolhidos


def json_para_reaproveitar(controle, numero) -> Path | None:
    """O JSON de uma entrega que falhou (`erro_envio`), se o arquivo ainda existe: dispensa coletar o processo de novo."""
    linha = controle.linha(numero)
    if not linha or linha["status"] != "erro_envio" or not linha["arquivo_entrada"]:
        return None
    arquivo = Path(linha["arquivo_entrada"])
    return arquivo if arquivo.is_file() else None


def entregar(arquivo) -> bool:
    """Copia o JSON para a pasta do SharePoint sincronizada, se configurada no .env. True se copiou."""
    if config.SHAREPOINT_PASTA_ENTRADA:
        destino = copiar_para_sharepoint(arquivo, config.SHAREPOINT_PASTA_ENTRADA)
        log.info("Entrada copiada para o SharePoint: %s", destino)
        return True
    return False


def _processar(numero, sei, controle, reaproveitar=None) -> tuple[bool, bool]:
    """Coleta (ou reaproveita o JSON de uma entrega que falhou), exporta e entrega um processo.

    Devolve (entregue, falhou): `entregue` é True se o JSON foi copiado para o SharePoint; `falhou`, se a coleta ou a
    entrega deu erro. Cada passo vai para o historico do banco.
    """
    try:
        if reaproveitar is not None:
            arquivo = reaproveitar
            gerado = datetime.fromtimestamp(arquivo.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            log.info("JSON reaproveitado, sem coletar o processo de novo (gerado em %s): %s", gerado, arquivo)
            controle.registrar_evento(numero, "json_reaproveitado", "ok", f"{arquivo.name}, gerado em {gerado}")
        else:
            processo = sei.coletar_processo(numero)
            if processo is None:
                controle.salvar(numero, "erro_coleta", erro="Falha na coleta")
                controle.registrar_evento(numero, "coleta", "erro", "Falha na coleta")
                return False, True
            controle.registrar_evento(numero, "coleta", "ok", f"{len(processo.documentos)} documento(s)")
            arquivo = exportar_para_automate(processo, config.PASTA_AUTOMATE_ENTRADA)
            log.info("Entrada criada: %s", arquivo)
            controle.registrar_evento(numero, "json_gerado", "ok", arquivo.name)
            sei.apagar_downloads(numero)  # o JSON já tem o texto: nada mais precisa dos anexos em disco
        try:
            entregue = entregar(arquivo)
        except Exception as erro:
            log.error("Erro ao enviar %s: %s", numero, erro)
            controle.salvar(numero, "erro_envio", arquivo_entrada=str(arquivo), erro=str(erro))
            controle.registrar_evento(numero, "entrega", "erro", str(erro))
            return False, True
        if entregue:
            controle.registrar_evento(numero, "entrega", "ok", "copiado para o SharePoint")
        else:
            controle.registrar_evento(numero, "entrega", "aviso", "SHAREPOINT_PASTA_ENTRADA vazia: JSON não copiado")
        controle.salvar(numero, "exportado", arquivo_entrada=str(arquivo))
        return entregue, False
    except Exception as erro:
        log.exception("Erro ao processar %s", numero)
        controle.salvar(numero, "erro_coleta", erro=str(erro))
        controle.registrar_evento(numero, "coleta", "erro", str(erro))
        return False, True


def _registrar(resultado, controle=None):
    mensagem = (
        "Análise %s (processo %s): %d correção(ões), %d erro(s), %d aviso(s). Relatório: %s.validacao.txt"
        % (resultado.arquivo, resultado.numero or "?", len(resultado.correcoes), len(resultado.erros),
           len(resultado.avisos), resultado.arquivo.rsplit(".", 1)[0])
    )
    (log.error if resultado.erros else log.warning if resultado.avisos else log.info)(mensagem)
    for problema in resultado.problemas:
        log.info("    %s", problema)
    enviado = None  # None: o envio ao Teams nem foi tentado
    if teams.configurado():
        enviado = teams.enviar_resultado(resultado)
        if enviado:
            log.info("Análise %s enviada pelo Teams para %s.", resultado.arquivo, ", ".join(config.TEAMS_DESTINATARIOS))
        else:
            log.warning("Análise %s NÃO foi enviada pelo Teams (veja o log de erros).", resultado.arquivo)
    if controle is not None:
        try:
            if not saidas.registrar_no_banco(controle, resultado, enviado):
                log.warning("Processo %s não está no banco; o status dele não foi atualizado.", resultado.numero or "?")
        except Exception:
            log.exception("Não foi possível atualizar o banco com a análise %s.", resultado.arquivo)


def processar_saidas(entregues, antes, controle=None):
    """Espera as análises NOVAS dos processos `entregues` na pasta de saída e corrige/valida as que chegarem.

    O que já estava na pasta (`antes`) e as análises de outros processos são ignorados. Se `controle` vier, cada
    análise que chega marca o processo como `analisado` no banco.
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
            entregues, antes, config.SAIDA_ESPERA_MINUTOS * 60, config.SAIDA_INTERVALO_SEGUNDOS,
            ao_processar=lambda resultado: _registrar(resultado, controle),
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
    _configurar_log()
    _avisar_texto_modelo()
    args = argumentos()
    credencial = obter_credenciais()
    if credencial is None:
        return 1
    usuario, senha = credencial
    antes = saidas.impressoes_existentes(config.SHAREPOINT_PASTA_SAIDA)  # o que já estava na saída antes desta execução
    entregues = []  # processos cujo JSON foi copiado para o SharePoint: as análises deles virão da pasta de saída
    sei = SEIService(config.PASTA_DOWNLOADS, config.LIMITE_TEXTO_DOCUMENTO, config.HEADLESS)
    controle = ControleProcessos(config.CAMINHO_BANCO)
    modo = "processo" if args.processo else config.SEI_MODO
    controle.iniciar_execucao(modo, f"processo={args.processo or '-'} reanalisar={args.reanalisar} sem_saida={args.sem_saida}")
    codigo = 1  # só passa a 0 se a execução chegar ao fim sem nenhum processo com falha
    falhas = []  # processos cuja coleta ou entrega deu erro nesta execução
    try:  # o banco fica aberto até o fim da espera: cada análise que chega atualiza a linha do processo
        try:
            if not sei.autenticar(usuario, senha, config.SEI_ORGAO, config.SEI_UNIDADE):
                log.error("Não foi possível autenticar no SEI. Se a senha mudou, atualize-a: python -m sei.credenciais --cadastrar")
                return 1
            del senha
            processos = escolher_processos(sei, controle, args.processo, args.reanalisar, config.TENTATIVAS_MAXIMAS)
            log.info("%d processo(s) para exportar.", len(processos))
            for numero in processos:
                controle.registrar_evento(numero, "selecionado", "ok", modo)
                # --processo e --reanalisar pedem uma coleta nova; sem eles, o JSON de uma entrega que falhou serve
                reaproveitar = None if (args.processo or args.reanalisar) else json_para_reaproveitar(controle, numero)
                entregue, falhou = _processar(numero, sei, controle, reaproveitar)
                if entregue:
                    entregues.append(numero)
                if falhou:
                    falhas.append(numero)
        finally:
            sei.fechar()  # o navegador não precisa ficar aberto durante a espera pelas análises
        if not args.sem_saida:
            processar_saidas(entregues, antes, controle)
        if falhas:
            log.error("%d processo(s) com falha nesta execução: %s", len(falhas), ", ".join(falhas))
        codigo = 1 if falhas else 0
        return codigo
    finally:
        controle.finalizar_execucao(codigo)
        controle.fechar()


if __name__ == "__main__":
    raise SystemExit(main())
