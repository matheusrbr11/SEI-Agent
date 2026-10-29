"""Teste avulso: o agente consegue logar no SEI com a tela do Windows bloqueada?

Como usar: rode este arquivo, dê Win+L em até 10 s e volte a logar depois de uns 60 s.
Usa o mesmo caminho do agente: lê a senha do Gerenciador de Credenciais, abre o navegador (sem headless), faz o
login no SEI e lê o Controle de Processos. Também confere se as pastas de entrada e saída do OneDrive abrem.
Não altera nada no SEI, não grava nas pastas do OneDrive e não grava a senha em lugar nenhum.
O resultado vai para teste_tela_bloqueada.log, ao lado deste arquivo. Pode apagá-lo depois do teste.
"""
import os
import subprocess
import time
import traceback
from datetime import datetime
from pathlib import Path

import config
from sei import credenciais
from sei.sei_service import SEIService

PASTA = Path(__file__).resolve().parent
LOG = PASTA / "teste_tela_bloqueada.log"
PRINT = PASTA / "teste_tela_bloqueada.png"
ESPERA = 10  # segundos para dar Win+L


def registrar(texto: str) -> None:
    linha = f"{datetime.now():%H:%M:%S}  {texto}"
    print(linha, flush=True)
    with LOG.open("a", encoding="utf-8") as arquivo:
        arquivo.write(linha + "\n")


def tela_bloqueada() -> bool:
    """A tela de bloqueio do Windows é o processo LogonUI.exe: ele só existe enquanto a tela está bloqueada."""
    saida = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq LogonUI.exe", "/NH"], capture_output=True, text=True, check=False
    ).stdout
    return "LogonUI.exe" in saida


def verificar_pasta(nome: str, pasta: Path | None) -> None:
    """Confere se a pasta do OneDrive está acessível. Não grava nada nela: um arquivo novo na entrada dispararia o fluxo."""
    if pasta is None:
        registrar(f"OneDrive {nome}: não configurada no .env.")
        return
    try:
        existe = pasta.is_dir()
        registrar(f"OneDrive {nome}: {'existe' if existe else 'NÃO EXISTE'} ({pasta})")
        if not existe:
            return
        arquivos = sorted((a for a in pasta.iterdir() if a.is_file()), key=lambda a: a.stat().st_mtime, reverse=True)
        registrar(f"OneDrive {nome}: {len(arquivos)} arquivo(s) listado(s).")
        if arquivos:  # ler o conteúdo confirma que o OneDrive baixa o arquivo, e não só mostra o nome
            lido = len(arquivos[0].read_bytes())
            registrar(f"OneDrive {nome}: leu {arquivos[0].name} ({lido} bytes).")
        registrar(f"OneDrive {nome}: permissão de escrita: {os.access(pasta, os.W_OK)}")
    except Exception:
        registrar(f"OneDrive {nome}: FALHOU\n" + traceback.format_exc())


def main() -> None:
    LOG.write_text("", encoding="utf-8")
    registrar(f"Começou. Dê Win+L agora; o teste inicia em {ESPERA} s.")
    time.sleep(ESPERA)
    registrar(f"Iniciando. Tela bloqueada: {tela_bloqueada()}")
    verificar_pasta("entrada", config.SHAREPOINT_PASTA_ENTRADA)
    verificar_pasta("saída", config.SHAREPOINT_PASTA_SAIDA)
    sei = None
    try:
        usuario = config.SEI_USUARIO
        senha = credenciais.obter(usuario) if usuario else None
        registrar(f"Usuário preenchido: {bool(usuario)}. Senha lida do Gerenciador de Credenciais: {bool(senha)}")
        if not senha:
            raise RuntimeError("Sem usuário no .env ou sem senha cadastrada (python -m sei.credenciais --cadastrar).")
        sei = SEIService(config.PASTA_DOWNLOADS, config.LIMITE_TEXTO_DOCUMENTO, False)
        driver = sei.sei.driver
        registrar("Navegador aberto.")
        driver.save_screenshot(str(PRINT))
        registrar(f"Print do navegador salvo ({PRINT.name}).")
        autenticou = sei.autenticar(usuario, senha, config.SEI_ORGAO, config.SEI_UNIDADE)
        del senha
        registrar(f"Login no SEI: {'OK' if autenticou else 'RECUSADO'}. Tela bloqueada: {tela_bloqueada()}")
        if not autenticou:
            raise RuntimeError("O SEI não aceitou o login.")
        controle = sei.carregar_controle_processos()
        registrar(f"Controle de Processos lido: {len(controle)} processo(s). Tela bloqueada: {tela_bloqueada()}")
        driver.save_screenshot(str(PRINT))
        registrar(f"Página do SEI: {driver.title!r}")
        registrar("RESULTADO: funcionou.")
    except Exception:
        registrar("RESULTADO: FALHOU\n" + traceback.format_exc())
    finally:
        if sei is not None:
            sei.fechar()
        registrar("Navegador fechado. Fim.")


if __name__ == "__main__":
    main()
