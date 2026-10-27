"""Extração, por regra fixa, de datas, destinatários e prazos dos textos dos documentos do SEI."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

# Assinatura eletrônica do SEI: "Documento assinado eletronicamente por Fulano, Cargo, em 04/08/2026, às 17:08".
_ASSINATURA = re.compile(r"assinado\s+eletronicamente\s+por", re.I)
# Cada signatário vem como "em dd/mm/aaaa, às hh:mm"; "Criado por ... em dd/mm/aaaa hh:mm:ss" não tem "às".
_EM_DATA = re.compile(r"\bem\s+(\d{2})/(\d{2})/(\d{4}),?\s+às\s+\d{1,2}:\d{2}")
_JANELA_ASSINATURA = 400

# O endereçamento fica em linhas curtas no início: "À SEFAZ/SUPCONFI,", "Ao ...", "Com vistas à ...".
_LINHAS_DESTINO = 15
_TAMANHO_MAXIMO_DESTINO = 160
_SO_MARCADOR = re.compile(r"^(?:à|às|ao|aos)$", re.I)
_DESTINO = re.compile(r"^(?:à|às|ao|aos|com\s+vistas\s+(?:à|ao)|c/\s*vistas\s+(?:à|ao))\s+\S", re.I)

# Data (dd/mm/aaaa ou dd/mm/aa) perto de uma palavra que indica prazo.
_PALAVRA_DE_PRAZO = re.compile(r"\b(?:prazo|até\s+o\s+dia|limite|vencimento|no\s+máximo)\b", re.I)
_DATA = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?![\d/])")
_HORA_DEPOIS = re.compile(r",?\s+às\s+\d{1,2}:\d{2}")
_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_JANELA_PRAZO = 120
_TRECHO_ANTES = 110
_TRECHO_DEPOIS = 40

# Unidades que mudaram de nome: o antigo e o atual são a MESMA unidade. Só a sigla em maiúsculas, fora de e-mails.
NOMES_ATUAIS = {"SUPCONC": "SUPCONFI", "SUPGO": "SUPHOB", "SUPAEF": "SUPADFIN"}
_PARES_DE_NOMES = re.compile("|".join(
    rf"{antigo}\s*/\s*{atual}|{atual}\s*/\s*{antigo}|{antigo}\s*\(\s*{atual}\s*\)|{atual}\s*\(\s*{antigo}\s*\)"
    for antigo, atual in NOMES_ATUAIS.items()
))
_NOME_ANTIGO = re.compile(r"(?<![\w.@])(" + "|".join(NOMES_ATUAIS) + r")(?![\w@-]|\.\w)")


def _data(dia: str, mes: str, ano: str) -> date | None:
    numero_ano = int(ano)
    if numero_ano < 100:
        numero_ano += 2000
    try:
        return date(numero_ano, int(mes), int(dia))
    except ValueError:
        return None


def data_assinatura(texto: str | None) -> date | None:
    """Data da assinatura eletrônica do documento; havendo mais de um signatário, a mais recente."""
    texto = texto or ""
    datas = []
    for assinatura in _ASSINATURA.finditer(texto):
        for achada in _EM_DATA.finditer(texto, assinatura.end(), assinatura.end() + _JANELA_ASSINATURA):
            if data := _data(*achada.groups()):
                datas.append(data)
    return max(datas) if datas else None


def destinatarios(texto: str | None) -> list[str]:
    """Linhas de endereçamento do documento ("À ...", "Ao ...", "Com vistas à ..."), na grafia da fonte."""
    linhas = [linha.strip() for linha in (texto or "").splitlines() if linha.strip()][:_LINHAS_DESTINO]
    achados: list[str] = []
    for posicao, linha in enumerate(linhas):
        if _SO_MARCADOR.match(linha) and posicao + 1 < len(linhas):
            linha = f"{linha} {linhas[posicao + 1]}"  # ofícios: "Ao" sozinho e o destinatário na linha de baixo
        if len(linha) <= _TAMANHO_MAXIMO_DESTINO and _DESTINO.match(linha):
            limpa = linha.rstrip(" ,:;.")
            if limpa not in achados:
                achados.append(limpa)
    return achados


def prazos_no_texto(texto: str | None) -> list[tuple[date, str]]:
    """Datas que aparecem logo depois de "prazo", "até o dia", "limite", "vencimento" ou "no máximo".

    Devolve (data, trecho) sem repetir datas. Quem interpreta qual prazo vale é a IA; aqui só se acha e se
    calcula, porque a aritmética de datas é regra fixa.
    """
    plano = re.sub(r"\s+", " ", texto or "")
    achados: dict[date, str] = {}
    for palavra in _PALAVRA_DE_PRAZO.finditer(plano):
        for achada in _DATA.finditer(plano, palavra.end(), palavra.end() + _JANELA_PRAZO):
            data = _data(*achada.groups())
            if not data or _HORA_DEPOIS.match(plano, achada.end()):  # "em 09/09/2026, às 18:46" é assinatura
                continue
            achados.setdefault(data, plano[max(0, achada.start() - _TRECHO_ANTES):achada.end() + _TRECHO_DEPOIS].strip())
            break  # só a primeira data depois da palavra; as seguintes costumam ser de outro assunto
    return list(achados.items())


def dominios_de_email(texto: str | None) -> list[str]:
    """Domínios dos e-mails citados no texto (ex.: "tcerj.tc.br"), sem repetir; pista de quem expediu o documento."""
    achados: list[str] = []
    for dominio in _EMAIL.findall(texto or ""):
        dominio = dominio.lower().rstrip(".")
        if dominio not in achados:
            achados.append(dominio)
    return achados


def _trocar_nomes(texto: str) -> str:
    texto = _PARES_DE_NOMES.sub(lambda par: next(a for a in NOMES_ATUAIS.values() if a in par.group(0)), texto)
    return _NOME_ANTIGO.sub(lambda nome: NOMES_ATUAIS[nome.group(1)], texto)


def _normalizador(protegidos):
    """Função que troca os nomes antigos pelos atuais, exceto dentro dos nomes de documentos (que ficam como na fonte)."""
    nomes = sorted({p for p in protegidos if p}, key=len, reverse=True)
    if not nomes:
        return _trocar_nomes
    padrao = re.compile("(" + "|".join(re.escape(nome) for nome in nomes) + ")")
    return lambda texto: "".join(
        parte if indice % 2 else _trocar_nomes(parte) for indice, parte in enumerate(padrao.split(texto))
    )


def nomes_antigos_em(texto: str, protegidos=()) -> list[str]:
    """Nomes antigos de unidades que ainda aparecem no texto, fora dos nomes de documentos (`protegidos`)."""
    for nome in sorted({p for p in protegidos if p}, key=len, reverse=True):
        texto = texto.replace(nome, " ")
    return sorted({achado.group(1) for achado in _NOME_ANTIGO.finditer(texto)})


def usar_nome_atual(texto: str, protegidos=()) -> str:
    """Troca SUPCONC→SUPCONFI, SUPGO→SUPHOB e SUPAEF→SUPADFIN, sem mexer em e-mails como supconc.subtes@..."""
    return _normalizador(protegidos)(texto)


def usar_nome_atual_em(estrutura: Any, protegidos=()) -> Any:
    """Aplica usar_nome_atual a todas as strings de um dict/list aninhado; `protegidos` são nomes de documentos."""
    normalizar = _normalizador(protegidos)

    def aplicar(valor: Any) -> Any:
        if isinstance(valor, str):
            return normalizar(valor)
        if isinstance(valor, list):
            return [aplicar(item) for item in valor]
        if isinstance(valor, dict):
            return {chave: aplicar(item) for chave, item in valor.items()}
        return valor

    return aplicar(estrutura)
