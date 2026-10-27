import pytest
from selenium.common.exceptions import ElementClickInterceptedException, NoSuchFrameException
from selenium.webdriver.common.by import By

from sei.modelos import DocumentoSEI
from sei.sei_service import SEIService


class _SEIFalso:
    """Imita o jupiter: grava <nome>.pdf na pasta atual, sobrescrevendo se já existir."""

    def baixar_documento(self, nome):
        with open(f"{nome}.pdf", "wb") as arquivo:
            arquivo.write(b"%PDF-falso")
        return True


def _servico(tmp_path, monkeypatch):
    servico = SEIService.__new__(SEIService)
    servico.sei = _SEIFalso()
    monkeypatch.setattr("sei.sei_service.extrair_conteudo", lambda caminho: "texto extraido")
    return servico


def test_download_novo_extrai_texto(tmp_path, monkeypatch):
    doc = _servico(tmp_path, monkeypatch)._baixar_e_extrair(DocumentoSEI(nome="Doc"), tmp_path)
    assert doc.texto == "texto extraido"
    assert doc.origem_texto == "arquivo"


def test_download_que_sobrescreve_arquivo_existente_extrai_texto(tmp_path, monkeypatch):
    (tmp_path / "Doc.pdf").write_bytes(b"%PDF-antigo-com-tamanho-diferente")
    doc = _servico(tmp_path, monkeypatch)._baixar_e_extrair(DocumentoSEI(nome="Doc"), tmp_path)
    assert doc.texto == "texto extraido"
    assert doc.arquivo_local.endswith("Doc.pdf")


class _DriverFalso:
    def __init__(self, unidades=None, falha=False):
        self.unidades, self.falha = unidades or {}, falha

    def execute_script(self, js):
        if self.falha:
            raise RuntimeError("iframe indisponível")
        return self.unidades


class _SEIArvoreFalsa:
    def __init__(self, driver):
        self.driver = driver
        self.iframes = []

    def sair_iframe(self):
        self.iframes.append("sair")

    def entrar_iframe(self, xpath):
        self.iframes.append(xpath)


def test_unidades_geradoras_le_da_arvore(tmp_path, monkeypatch):
    servico = _servico(tmp_path, monkeypatch)
    servico.sei = _SEIArvoreFalsa(_DriverFalso({"Doc": "SEFAZ/SUPCONC"}))
    assert servico._unidades_geradoras() == {"Doc": "SEFAZ/SUPCONC"}
    assert servico.sei.iframes[-1] == "sair"


def test_unidades_geradoras_falha_nao_derruba_coleta(tmp_path, monkeypatch):
    servico = _servico(tmp_path, monkeypatch)
    servico.sei = _SEIArvoreFalsa(_DriverFalso(falha=True))
    assert servico._unidades_geradoras() == {}


class _NoFalso:
    def __init__(self, id_, visivel=True):
        self.id, self.visivel = id_, visivel

    def get_attribute(self, nome):
        return self.id

    def is_displayed(self):
        return self.visivel


class _PastaFalsa:
    title = "Abrir Pasta"


class _BotaoFalso:
    pass


class _ArvoreDriverFalso:
    """Como o SEI: "Abrir todas as Pastas" troca os títulos na hora, mas os documentos de dentro delas
    só aparecem depois de `atraso` consultas à árvore."""

    def __init__(self, pastas=3, atraso=0, botao=True, arvore_antiga=(), navegacao=0):
        self.pastas = [_PastaFalsa() for _ in range(pastas)]
        self.botao = [_BotaoFalso()] if botao else []
        self.nos = [_NoFalso(i) for i in arvore_antiga] or [_NoFalso("anchor0")]
        self.arvore_antiga = bool(arvore_antiga)
        self.atraso, self.pendentes, self.cliques = atraso, [], 0
        self.navegacao, self.navegando = navegacao, 0  # consultas ao iframe que falham após o clique
        self.switch_to = self

    def default_content(self):
        pass

    def frame(self, elemento):
        pass

    def find_element(self, by, xpath):
        if self.navegando > 0:
            self.navegando -= 1
            raise NoSuchFrameException("a árvore está recarregando")
        return object()

    def find_elements(self, by, xpath):
        if "Abrir Pasta" in xpath:
            return [p for p in self.pastas if p.title == "Abrir Pasta"]
        if "Abrir todas as Pastas" in xpath:
            return self.botao
        for pendente in self.pendentes:
            pendente[0] -= 1
        self.nos += [no for restantes, no in self.pendentes if restantes <= 0]
        self.pendentes = [p for p in self.pendentes if p[0] > 0]
        return list(self.nos)

    def execute_script(self, js, elemento):
        assert isinstance(elemento, _BotaoFalso)
        self.cliques += 1
        self.navegando = self.navegacao
        for numero, pasta in enumerate(self.pastas):
            pasta.title = "Fechar Pasta"
            self.pendentes.append([self.atraso, _NoFalso(f"doc{numero}")])


class _SEIArvoreAbrivel(_SEIArvoreFalsa):
    def _aguardar_sei(self):
        pass


def _servico_arvore(tmp_path, monkeypatch, driver):
    servico = _servico(tmp_path, monkeypatch)
    servico.sei = _SEIArvoreAbrivel(driver)
    return servico


def test_abrir_todas_clica_uma_vez_no_botao_e_abre_as_pastas(tmp_path, monkeypatch):
    driver = _ArvoreDriverFalso(pastas=3)
    _servico_arvore(tmp_path, monkeypatch, driver)._abrir_todas_as_pastas(espera=5)
    assert driver.cliques == 1
    assert all(p.title == "Fechar Pasta" for p in driver.pastas)


def test_abrir_todas_espera_documentos_carregarem(tmp_path, monkeypatch):
    driver = _ArvoreDriverFalso(pastas=3, atraso=3)
    _servico_arvore(tmp_path, monkeypatch, driver)._abrir_todas_as_pastas(espera=10)
    assert not driver.pendentes  # todos os documentos já apareceram quando a espera termina
    assert len(driver.nos) == 1 + 3


def test_abrir_todas_nao_clica_sem_pastas_fechadas(tmp_path, monkeypatch):
    driver = _ArvoreDriverFalso(pastas=0)
    _servico_arvore(tmp_path, monkeypatch, driver)._abrir_todas_as_pastas(espera=5)
    assert driver.cliques == 0


def test_abrir_todas_sem_botao_nao_quebra(tmp_path, monkeypatch):
    driver = _ArvoreDriverFalso(pastas=2, botao=False)
    _servico_arvore(tmp_path, monkeypatch, driver)._abrir_todas_as_pastas(espera=5)
    assert driver.cliques == 0


def test_abrir_todas_que_nao_carrega_respeita_o_limite_de_tempo(tmp_path, monkeypatch):
    driver = _ArvoreDriverFalso(pastas=2)
    driver.execute_script = lambda js, elemento: None
    _servico_arvore(tmp_path, monkeypatch, driver)._abrir_todas_as_pastas(espera=1)
    assert all(p.title == "Abrir Pasta" for p in driver.pastas)


def test_abrir_todas_espera_arvore_nova_substituir_a_anterior(tmp_path, monkeypatch):
    driver = _ArvoreDriverFalso(pastas=2, arvore_antiga=["anchor9"])
    servico = _servico_arvore(tmp_path, monkeypatch, driver)
    anteriores = servico._ids_arvore()
    assert anteriores == {"anchor9"}
    consultas = []
    antigo_find = driver.find_elements

    def find_elements(by, xpath):
        consultas.append(xpath)
        if len(consultas) == 3:
            driver.nos = [_NoFalso("anchor0")]
        return antigo_find(by, xpath)

    driver.find_elements = find_elements
    servico._abrir_todas_as_pastas(anteriores, espera=5)
    assert driver.cliques == 1


def test_abrir_todas_sobrevive_ao_iframe_recarregando(tmp_path, monkeypatch):
    driver = _ArvoreDriverFalso(pastas=3, atraso=1, navegacao=3)
    _servico_arvore(tmp_path, monkeypatch, driver)._abrir_todas_as_pastas(espera=10)
    assert not driver.pendentes
    assert all(p.title == "Fechar Pasta" for p in driver.pastas)


class _DriverDiagnostico:
    def execute_script(self, js):
        return "[]\n\n<div id='divArvore'></div>"

    def save_screenshot(self, caminho):
        open(caminho, "wb").write(b"png")


def test_falha_ao_analisar_documentos_salva_diagnostico_e_repropaga(tmp_path, monkeypatch):
    servico = _servico(tmp_path, monkeypatch)
    servico.pasta_downloads = tmp_path
    servico.limite_texto = 80
    servico.sei = _SEIArvoreFalsa(_DriverDiagnostico())
    servico.sei.pesquisar_processo = lambda numero: None
    servico.sei._aguardar_sei = lambda: None

    def analisar():
        raise RuntimeError("element not interactable")

    servico._analisar_documentos = analisar
    servico._abrir_todas_as_pastas = lambda anteriores: None
    servico._ids_arvore = lambda: frozenset()
    with pytest.raises(RuntimeError):
        servico._ler_documentos("SEI-040009/001741/2026")
    pasta = tmp_path / "SEI-040009_001741_2026"
    assert (pasta / "diagnostico_arvore.txt").exists()
    assert (pasta / "diagnostico_tela.png").exists()


class _LinkFalso:
    def __init__(self, driver, id_, texto):
        self.driver, self.id, self.text = driver, id_, texto

    def get_attribute(self, nome):
        return self.id

    def click(self):
        if self.id in self.driver.cobertos:
            raise ElementClickInterceptedException("coberto pela barra de rolagem")
        self.driver.cliques.append(self.id)
        self.driver.atual = self.text


class _CorpoFalso:
    def __init__(self, driver):
        self.driver = driver

    @property
    def text(self):
        return f"texto de {self.driver.atual}"


class _DriverArvoreDocumentos:
    def __init__(self, cobertos=(), planilhas=()):
        self.cliques, self.atual, self.cobertos, self.centralizados = [], None, set(cobertos), []
        self.planilhas = list(planilhas)
        self.links = [
            _LinkFalso(self, "anchorPASTA1", "I"),
            _LinkFalso(self, "anchor10", "Doc A"),
            _LinkFalso(self, "anchorPASTA2", "II"),
            _LinkFalso(self, "anchor20", "Doc B"),
        ]

    def find_elements(self, by, xpath):
        if "anchorPASTA" in xpath:  # o xpath exclui os links de pasta
            return [link for link in self.links if not link.id.startswith("anchorPASTA")]
        return list(self.links)

    def find_element(self, by, valor):
        if by == By.ID:
            return next(link for link in self.links if link.id == valor)
        return _CorpoFalso(self)

    def execute_script(self, js, link=None):
        if "documento_excel.svg" in js:
            return self.planilhas
        if "scrollIntoView" in js:
            self.centralizados.append(link.id)
        else:  # clique por JavaScript ignora o que estiver cobrindo o link
            self.cliques.append(link.id)
            self.atual = link.text


def test_analisar_documentos_nao_clica_nos_nomes_das_pastas(tmp_path, monkeypatch):
    driver = _DriverArvoreDocumentos()
    servico = _servico(tmp_path, monkeypatch)
    servico.sei = _SEIArvoreFalsa(driver)
    textos = servico._analisar_documentos()
    assert textos == {"Doc A": "texto de Doc A", "Doc B": "texto de Doc B"}
    assert driver.cliques == ["anchor10", "anchor20"]
    assert servico.sei.iframes[-1] == "sair"


def test_analisar_documentos_centraliza_link_e_usa_js_quando_clique_e_interceptado(tmp_path, monkeypatch):
    driver = _DriverArvoreDocumentos(cobertos=["anchor20"])
    servico = _servico(tmp_path, monkeypatch)
    servico.sei = _SEIArvoreFalsa(driver)
    textos = servico._analisar_documentos()
    assert textos == {"Doc A": "texto de Doc A", "Doc B": "texto de Doc B"}
    assert driver.centralizados == ["anchor10", "anchor20"]
    assert driver.cliques == ["anchor10", "anchor20"]


def test_download_rola_a_arvore_ate_o_documento_antes_de_baixar(tmp_path, monkeypatch):
    ordem = []
    driver = _DriverArvoreDocumentos()
    driver.execute_script = lambda js, link: ordem.append(("rolar", link.id))
    servico = _servico(tmp_path, monkeypatch)
    servico.sei = _SEIArvoreFalsa(driver)

    def baixar(nome):
        ordem.append(("baixar", nome))
        return False

    servico.sei.baixar_documento = baixar
    servico._baixar_e_extrair(DocumentoSEI(nome="Doc B"), tmp_path)
    assert ordem == [("rolar", "anchor20"), ("baixar", "Doc B")]


def test_download_que_o_sei_nao_fez_gera_aviso(tmp_path, monkeypatch, caplog):
    servico = _servico(tmp_path, monkeypatch)
    servico.sei.baixar_documento = lambda nome: False
    doc = servico._baixar_e_extrair(DocumentoSEI(nome="Doc"), tmp_path)
    assert doc.texto is None
    assert "O SEI não baixou Doc" in caplog.text


def test_analisar_documentos_pula_planilhas_excel_sem_clicar(tmp_path, monkeypatch):
    driver = _DriverArvoreDocumentos(planilhas=["anchor10"])
    servico = _servico(tmp_path, monkeypatch)
    servico.sei = _SEIArvoreFalsa(driver)
    textos = servico._analisar_documentos()
    assert textos == {"Doc A": None, "Doc B": "texto de Doc B"}  # a planilha segue na lista, na mesma posição
    assert driver.cliques == ["anchor20"]


def test_analisar_documentos_com_falha_ao_achar_planilhas_segue_sem_pular_nada(tmp_path, monkeypatch):
    driver = _DriverArvoreDocumentos()
    driver.execute_script = lambda js, link=None: (_ for _ in ()).throw(RuntimeError("js falhou")) if "excel" in js else None
    servico = _servico(tmp_path, monkeypatch)
    servico.sei = _SEIArvoreFalsa(driver)
    assert servico._planilhas() == set()


def test_planilha_entra_no_processo_sem_texto_e_sem_download(tmp_path, monkeypatch):
    servico = _servico(tmp_path, monkeypatch)
    servico.pasta_downloads = tmp_path
    servico.limite_texto = 80
    servico.sei = _SEIArvoreFalsa(None)
    servico.sei.pesquisar_processo = lambda numero: None
    servico.sei._aguardar_sei = lambda: None
    servico.sei.baixar_documento = lambda nome: (_ for _ in ()).throw(AssertionError("não deve baixar"))
    servico._ids_arvore = lambda: frozenset()
    servico._abrir_todas_as_pastas = lambda anteriores: None
    servico._analisar_documentos = lambda: {"Planilha": None, "Doc": "x" * 100}
    servico._unidades_geradoras = lambda: {"Planilha": "SEFAZ/SUBTES"}
    planilha, doc = servico._ler_documentos("SEI-040009/001741/2026")
    assert (planilha.nome, planilha.texto, planilha.origem_texto, planilha.unidade) == ("Planilha", None, "arquivo", "SEFAZ/SUBTES")
    assert planilha.motivo_sem_texto == "planilha Excel não lida"
    assert doc.texto == "x" * 100


def _servico_com_downloads(tmp_path):
    servico = SEIService.__new__(SEIService)
    servico.pasta_downloads = tmp_path / "downloads"
    servico.pasta_downloads.mkdir()
    return servico


def test_apagar_downloads_remove_a_pasta_do_processo_e_so_ela(tmp_path):
    servico = _servico_com_downloads(tmp_path)
    for nome in ("SEI-1_2_3", "SEI-4_5_6"):
        (servico.pasta_downloads / nome).mkdir()
        (servico.pasta_downloads / nome / "Doc.pdf").write_bytes(b"%PDF-")
    servico.apagar_downloads("SEI-1/2/3")
    assert [p.name for p in servico.pasta_downloads.iterdir()] == ["SEI-4_5_6"]


def test_apagar_downloads_sem_pasta_do_processo_nao_faz_nada(tmp_path):
    servico = _servico_com_downloads(tmp_path)
    servico.apagar_downloads("SEI-1/2/3")
    assert servico.pasta_downloads.is_dir()


@pytest.mark.parametrize("numero", ["..", ".", ""])
def test_apagar_downloads_nunca_apaga_fora_da_pasta_de_downloads(tmp_path, numero):
    servico = _servico_com_downloads(tmp_path)
    (tmp_path / "importante.txt").write_text("x", encoding="utf-8")
    servico.apagar_downloads(numero)
    assert (tmp_path / "importante.txt").is_file() and servico.pasta_downloads.is_dir()
