"""Camada de coleta do SEI construída sobre jupiter-subtes."""
from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Optional

from jupiter import SEI
from jupiter.seilibrary_xpaths import xpaths_processos
from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from extratores.extrator import extrair_conteudo
from sei.modelos import MOTIVO_PLANILHA, DocumentoSEI, ProcessoSEI

logger = logging.getLogger("jupiter.agente.sei")


@contextlib.contextmanager
def _diretorio(pasta: Path):
    anterior = Path.cwd()
    pasta.mkdir(parents=True, exist_ok=True)
    os.chdir(pasta)
    try:
        yield
    finally:
        os.chdir(anterior)


def _estado(pasta: Path) -> dict[Path, tuple[int, int]]:
    """Mtime e tamanho de cada arquivo; permite notar também downloads que sobrescrevem um existente."""
    return {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in pasta.iterdir() if p.is_file()}


# Cada link de documento tem id "anchor<ID>" e a sigla da unidade geradora, ao lado, "anchorUG<ID>".
_JS_UNIDADES = """
const unidades = {};
for (const link of document.querySelectorAll('#divArvore a.infraArvoreNo')) {
  const sigla = document.getElementById('anchorUG' + link.id.replace('anchor', ''));
  if (sigla) unidades[link.innerText.trim()] = sigla.innerText.trim();
}
return unidades;
"""


# Ids dos links de planilhas Excel: o ícone é "icon<ID>" com documento_excel.svg e o link é "anchor<ID>".
# Clicar numa planilha faz o navegador baixá-la em vez de exibi-la, então elas não são lidas.
_JS_PLANILHAS = """
return [...document.querySelectorAll('#divArvore img[src*="documento_excel.svg"]')]
  .map(img => 'anchor' + img.id.replace('icon', ''));
"""

# Estado de cada link da árvore (tamanho, visibilidade) seguido do HTML dela, para diagnosticar cliques que falham.
_JS_DIAGNOSTICO = """
const nos = [...document.querySelectorAll('#divArvore a.infraArvoreNo')].map(a => {
  const r = a.getBoundingClientRect(), estilo = getComputedStyle(a);
  return {id: a.id, texto: a.innerText.trim().slice(0, 80), largura: r.width, altura: r.height,
          display: estilo.display, visibility: estilo.visibility};
});
const arvore = document.getElementById('divArvore');
return JSON.stringify(nos, null, 1) + '\\n\\n' + (arvore ? arvore.outerHTML : document.body.outerHTML);
"""

_XPATH_PASTA_FECHADA = '//*[contains(@title, "Abrir Pasta")]'
_XPATH_ABRIR_TODAS = '//a[.//img[@title="Abrir todas as Pastas"]]'  # o id do link varia por processo
_XPATH_DOCUMENTOS = "//div[@id = 'divArvore']//div//a[@class = 'infraArvoreNo']"
# Os nomes das pastas ("anchorPASTA1"...) também são links infraArvoreNo, mas clicar neles abre/fecha a pasta.
_XPATH_LINKS_DOCUMENTOS = "//div[@id = 'divArvore']//a[@class = 'infraArvoreNo' and not(starts-with(@id, 'anchorPASTA'))]"


def _nome_seguro(numero: str) -> str:
    return numero.replace("/", "_").replace(" ", "_")


class SEIService:
    def __init__(self, pasta_downloads: Path, limite_texto: int = 80, headless: bool = False):
        self.sei = SEI()
        self.sei.abrir_driver(headless=headless)
        self.pasta_downloads = Path(pasta_downloads)
        self.limite_texto = limite_texto
        self._cache_controle: dict[str, dict] = {}

    def autenticar(self, usuario: str, senha: str, orgao: str, unidade: str) -> bool:
        if not self.sei.logar_sei(usuario, senha, orgao):
            return False
        if unidade:
            self.sei.trocar_unidade(unidade)
        return True

    def fechar(self) -> None:
        try:
            self.sei.fechar_driver()
        except Exception:
            logger.debug("Falha ao fechar navegador.", exc_info=True)

    def carregar_controle_processos(self) -> list[dict]:
        linhas = self.sei.controlar_processos() or []
        self._cache_controle = {linha["processo"]: linha for linha in linhas}
        return linhas

    def listar_por_marcador(self, marcador: str) -> list[str]:
        linhas = self.sei.visualizar_processos_por_marcador(marcador) or []
        return [linha["processo"] for linha in linhas]

    def listar_todos(self) -> list[str]:
        return [linha["processo"] for linha in self.carregar_controle_processos()]

    def _centralizar_na_arvore(self, nome: str) -> None:
        """Rola a árvore até o documento: o baixar_documento do jupiter falha com links fora da área visível.

        A rolagem é instantânea porque o SEI usa rolagem animada, e o clique viria antes de ela terminar.
        """
        try:
            driver = self.sei.driver
            self.sei.sair_iframe()
            self.sei.entrar_iframe(xpaths_processos.iframe_arvore)
            for link in driver.find_elements(By.XPATH, _XPATH_LINKS_DOCUMENTOS):
                if nome in link.text:  # o mesmo critério do baixar_documento
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});", link)
                    return
        except Exception:
            logger.debug("Não foi possível rolar a árvore até %s.", nome, exc_info=True)

    def _baixar_e_extrair(self, doc: DocumentoSEI, pasta: Path) -> DocumentoSEI:
        try:
            self._centralizar_na_arvore(doc.nome)
            with _diretorio(pasta):
                antes = _estado(pasta)
                if not self.sei.baixar_documento(doc.nome):
                    logger.warning("O SEI não baixou %s.", doc.nome)
                    return doc
                depois = _estado(pasta)
                alterados = sorted(
                    (p for p, estado in depois.items() if antes.get(p) != estado),
                    key=lambda p: depois[p][0],
                )
            if alterados:
                arquivo = alterados[-1]
                doc.arquivo_local = str(arquivo)
                doc.texto = extrair_conteudo(arquivo) or None
                doc.origem_texto = "arquivo" if doc.texto else None
        except Exception:
            logger.warning("Não foi possível baixar %s", doc.nome, exc_info=True)
        return doc

    def _unidades_geradoras(self) -> dict[str, str]:
        """Sigla da unidade que gerou cada documento, indexada pelo nome na árvore."""
        try:
            self.sei.sair_iframe()
            self.sei.entrar_iframe(xpaths_processos.iframe_arvore)
            return self.sei.driver.execute_script(_JS_UNIDADES) or {}
        except Exception:
            logger.warning("Não foi possível ler as unidades geradoras.", exc_info=True)
            return {}
        finally:
            self.sei.sair_iframe()

    def _ids_arvore(self) -> frozenset[str]:
        """Ids dos nós da árvore atualmente na tela; vazio se não houver árvore."""
        driver = self.sei.driver
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(driver.find_element(By.XPATH, xpaths_processos.iframe_arvore))
            return frozenset(no.get_attribute("id") for no in driver.find_elements(By.XPATH, _XPATH_DOCUMENTOS))
        except WebDriverException:
            return frozenset()
        finally:
            with contextlib.suppress(WebDriverException):
                driver.switch_to.default_content()

    def _aguardar_arvore(self, anteriores: frozenset[str], espera: float) -> None:
        """Espera aparecer a árvore do processo pesquisado, e não a da página anterior."""
        def pronta(_):
            atuais = self._ids_arvore()
            return bool(atuais) and atuais != anteriores

        try:
            WebDriverWait(self.sei.driver, espera).until(pronta)
        except TimeoutException:
            logger.warning("A árvore do processo não carregou em %ss; seguindo mesmo assim.", espera)

    def _abrir_todas_as_pastas(self, anteriores: frozenset[str] = frozenset(), espera: float = 15) -> None:
        """Clica em "Abrir todas as Pastas" do SEI e espera, até `espera` segundos, a árvore recarregar.

        O botão é um link que recarrega a árvore com as pastas abertas; enquanto isso o iframe e os
        elementos mudam, então cada consulta reentra no iframe. A espera só termina com nenhuma pasta
        fechada, todos os documentos visíveis e a quantidade deles estável.
        """
        driver = self.sei.driver
        self._aguardar_arvore(anteriores, espera)
        self.sei.sair_iframe()
        self.sei.entrar_iframe(xpaths_processos.iframe_arvore)
        self.sei._aguardar_sei()
        fechadas = driver.find_elements(By.XPATH, _XPATH_PASTA_FECHADA)
        if not fechadas:
            return
        botao = driver.find_elements(By.XPATH, _XPATH_ABRIR_TODAS)
        if not botao:
            logger.warning("Botão 'Abrir todas as Pastas' não encontrado; %d pasta(s) seguem fechadas.", len(fechadas))
            return
        total = len(driver.find_elements(By.XPATH, _XPATH_DOCUMENTOS))
        anterior = [total]

        def carregado(d):
            try:
                d.switch_to.default_content()
                d.switch_to.frame(d.find_element(By.XPATH, xpaths_processos.iframe_arvore))
                nos = d.find_elements(By.XPATH, _XPATH_DOCUMENTOS)
                estavel = len(nos) == anterior[0]
                anterior[0] = len(nos)
                return (
                    estavel
                    and len(nos) > total
                    and not d.find_elements(By.XPATH, _XPATH_PASTA_FECHADA)
                    and all(no.is_displayed() for no in nos)
                )
            except WebDriverException:
                return False

        driver.execute_script("arguments[0].click();", botao[0])
        try:
            WebDriverWait(driver, espera).until(carregado)
        except TimeoutException:
            logger.warning("As pastas não terminaram de abrir em %ss; seguindo com a árvore como está.", espera)

    def _planilhas(self) -> set[str]:
        """Ids dos links de planilhas Excel da árvore (o iframe da árvore precisa estar aberto)."""
        try:
            return set(self.sei.driver.execute_script(_JS_PLANILHAS) or [])
        except Exception:
            logger.warning("Não foi possível identificar as planilhas da árvore.", exc_info=True)
            return set()

    def _analisar_documentos(self) -> dict[str, Optional[str]]:
        """Texto de cada documento da árvore, indexado pelo nome; None nas planilhas Excel, que são puladas.

        Substitui o analisar_documentos do jupiter, que também clica nos nomes das pastas: isso as fecha
        e deixa os documentos de dentro delas inclicáveis.
        """
        driver = self.sei.driver
        self.sei.sair_iframe()
        self.sei.entrar_iframe(xpaths_processos.iframe_arvore)
        links = [(link.get_attribute("id"), link.text) for link in driver.find_elements(By.XPATH, _XPATH_LINKS_DOCUMENTOS)]
        planilhas = self._planilhas()
        textos: dict[str, Optional[str]] = {}
        for id_link, nome in links:
            if id_link in planilhas:
                logger.info("Planilha Excel ignorada: %s", nome)
                textos[nome] = None
                continue
            self.sei.sair_iframe()
            self.sei.entrar_iframe(xpaths_processos.iframe_arvore)
            link = driver.find_element(By.ID, id_link)
            # Perto da borda do painel a barra de rolagem cobre o link; centralizá-lo evita o clique interceptado.
            # 'instant' porque o SEI rola de forma animada e o clique viria antes de a rolagem terminar.
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});", link)
            try:
                link.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", link)
            self.sei.sair_iframe()
            self.sei.entrar_iframe(xpaths_processos.iframe_conteudo_visualizacao)
            self.sei.entrar_iframe(xpaths_processos.iframe_visualizacao)
            textos[nome] = driver.find_element(By.TAG_NAME, "body").text
        self.sei.sair_iframe()
        logger.info("Análise de documentos concluída. %d documento(s) processado(s).", len(textos))
        return textos

    def _salvar_diagnostico(self, numero: str) -> None:
        """Guarda a árvore e um print da tela na pasta do processo; nunca levanta erro."""
        pasta = self.pasta_downloads / _nome_seguro(numero)
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            driver = self.sei.driver
            self.sei.sair_iframe()
            self.sei.entrar_iframe(xpaths_processos.iframe_arvore)
            (pasta / "diagnostico_arvore.txt").write_text(driver.execute_script(_JS_DIAGNOSTICO), encoding="utf-8")
            self.sei.sair_iframe()
            driver.save_screenshot(str(pasta / "diagnostico_tela.png"))
            logger.info("Diagnóstico da árvore salvo em %s", pasta)
        except Exception:
            logger.warning("Não foi possível salvar o diagnóstico da árvore.", exc_info=True)

    def _ler_documentos(self, numero: str) -> list[DocumentoSEI]:
        anteriores = self._ids_arvore()
        self.sei.pesquisar_processo(numero)
        self.sei._aguardar_sei()
        self._abrir_todas_as_pastas(anteriores)
        try:
            textos = self._analisar_documentos()
        except Exception:
            self._salvar_diagnostico(numero)
            raise
        unidades = self._unidades_geradoras()
        pasta = self.pasta_downloads / _nome_seguro(numero)
        documentos: list[DocumentoSEI] = []
        for nome, texto_original in textos.items():
            if texto_original is None:  # planilha Excel: mantém a posição na linha do tempo, sem ler nem baixar
                documentos.append(
                    DocumentoSEI(
                        nome=nome,
                        unidade=unidades.get(nome.strip()),
                        origem_texto="arquivo",
                        motivo_sem_texto=MOTIVO_PLANILHA,
                    )
                )
                continue
            texto = (texto_original or "").strip()
            doc = DocumentoSEI(nome=nome, unidade=unidades.get(nome.strip()))
            if len(texto) >= self.limite_texto:
                doc.texto = texto
                doc.origem_texto = "sei_html"
            else:
                doc = self._baixar_e_extrair(doc, pasta)
            documentos.append(doc)
        return documentos

    def coletar_processo(self, numero: str) -> Optional[ProcessoSEI]:
        meta = self._cache_controle.get(numero, {})
        processo = ProcessoSEI(
            numero=numero,
            tipo=meta.get("tipo"),
            especificacao=meta.get("especificacao"),
            interessados=meta.get("interessados"),
            anotacao=meta.get("anotacao"),
            marcadores=meta.get("marcadores"),
            atribuicao=meta.get("atribuicao"),
            ultima_movimentacao=meta.get("ultima_movimentacao"),
        )
        try:
            processo.documentos = self._ler_documentos(numero)
            logger.info("%s: %d documento(s) lido(s).", numero, len(processo.documentos))
            return processo
        except Exception:
            logger.exception("Falha ao coletar %s", numero)
            return None
