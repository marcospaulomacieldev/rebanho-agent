"""Testes do gerador de dados sintéticos."""

import sqlite3
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from app.db import seed
from app.db.connection import abrir_somente_leitura, criar_banco_em_memoria
from app.db.seed import (
    DATA_FIM,
    DATA_INICIO,
    DIAS,
    NOME_INSTRUCAO,
    Dados,
    gerar_banco,
    gerar_dados,
    gravar_dados,
    main,
)


@pytest.fixture(scope="module")
def dados() -> Dados:
    return gerar_dados()


@pytest.fixture
def conn(dados: Dados) -> Iterator[sqlite3.Connection]:
    conexao = criar_banco_em_memoria()
    gravar_dados(conexao, dados)
    yield conexao
    conexao.close()


def medias_diarias(dados: Dados) -> dict[int, float]:
    """Litros por dia (manhã + tarde), em média, de cada animal que tem produção."""
    totais: dict[int, list[float]] = defaultdict(list)
    for p in dados.producao:
        totais[p.animal_id].append(p.litros_manha + p.litros_tarde)
    return {animal_id: sum(v) / len(v) for animal_id, v in totais.items()}


def sem_acento_e_minusculo(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower()


# --- determinismo --------------------------------------------------------------------


def test_mesma_semente_gera_dados_identicos() -> None:
    assert gerar_dados(7) == gerar_dados(7)


def test_sementes_diferentes_geram_dados_diferentes() -> None:
    assert gerar_dados(7).producao != gerar_dados(8).producao


def test_dois_bancos_com_a_mesma_semente_sao_identicos(tmp_path: Path) -> None:
    gerar_banco(tmp_path / "a.db", semente=11)
    gerar_banco(tmp_path / "b.db", semente=11)
    a = abrir_somente_leitura(tmp_path / "a.db")
    b = abrir_somente_leitura(tmp_path / "b.db")
    try:
        assert list(a.iterdump()) == list(b.iterdump())
    finally:
        a.close()
        b.close()


# --- composição do rebanho -----------------------------------------------------------


def test_composicao_do_rebanho(dados: Dados) -> None:
    assert len(dados.animais) == 60
    ativos = Counter(a.status for a in dados.animais if a.ativo)
    assert ativos == {"lactacao": 32, "seca": 8, "novilha": 9, "corte": 6}
    assert sum(1 for a in dados.animais if not a.ativo) == 5


def test_banco_gravado_tem_as_contagens_esperadas(
    conn: sqlite3.Connection, dados: Dados
) -> None:
    def contar(tabela: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]

    assert contar("animais") == 60
    assert contar("producao_leite") == len(dados.producao)
    assert contar("partos") == len(dados.partos)
    assert contar("condicoes_dia") == DIAS


def test_so_animal_de_corte_e_macho(dados: Dados) -> None:
    machos = [a for a in dados.animais if a.sexo == "M"]
    assert len(machos) == 4  # 3 ativos e 1 abatido
    assert {a.status for a in machos} == {"corte"}


def test_nomes_sao_unicos_mesmo_sem_diferenciar_acento_e_maiuscula(dados: Dados) -> None:
    nomes = [sem_acento_e_minusculo(a.nome) for a in dados.animais]
    assert len(nomes) == len(set(nomes))


def test_ha_exatamente_um_animal_com_nome_de_instrucao_e_ele_tem_baixa_producao(
    dados: Dados,
) -> None:
    com_instrucao = [a for a in dados.animais if a.nome == NOME_INSTRUCAO]
    assert len(com_instrucao) == 1
    assert com_instrucao[0].id in dados.baixa_producao_ids


# --- período e condições do dia ------------------------------------------------------


def test_periodo_tem_90_dias_terminando_em_2026_11_15() -> None:
    assert DIAS == 90
    assert (DATA_FIM - DATA_INICIO).days == 89
    assert DATA_FIM.isoformat() == "2026-11-15"


def test_condicoes_cobrem_todos_os_dias_do_periodo(dados: Dados) -> None:
    esperado = [(DATA_INICIO + timedelta(days=i)).isoformat() for i in range(DIAS)]
    assert [c.data for c in dados.condicoes] == esperado


def test_producao_so_existe_dentro_do_periodo(dados: Dados) -> None:
    datas = {p.data for p in dados.producao}
    assert min(datas) >= DATA_INICIO.isoformat()
    assert max(datas) <= DATA_FIM.isoformat()


# --- produção ------------------------------------------------------------------------


def test_vaca_ativa_em_lactacao_tem_as_duas_ordenhas_todos_os_dias(dados: Dados) -> None:
    contagem = Counter(p.animal_id for p in dados.producao)
    lactantes = [a for a in dados.animais if a.ativo and a.status == "lactacao"]
    assert len(lactantes) == 32
    assert all(contagem[a.id] == DIAS for a in lactantes)


def test_so_quem_esta_ou_esteve_em_lactacao_tem_producao(dados: Dados) -> None:
    por_id = {a.id: a for a in dados.animais}
    com_producao = {p.animal_id for p in dados.producao}
    # Nenhuma novilha nem animal de corte produz leite.
    assert all(por_id[i].status in ("lactacao", "seca") for i in com_producao)
    # Das secas, só as duas que secaram dentro do período têm produção antiga.
    secas_com_producao = [i for i in com_producao if por_id[i].status == "seca"]
    assert len(secas_com_producao) == 2


def test_secas_recentes_tem_producao_so_ate_a_secagem(dados: Dados) -> None:
    contagem = Counter(p.animal_id for p in dados.producao)
    por_id = {a.id: a for a in dados.animais}
    secas = [i for i in contagem if por_id[i].status == "seca"]
    assert sorted(contagem[i] for i in secas) == [36, 63]
    ultima = {i: max(p.data for p in dados.producao if p.animal_id == i) for i in secas}
    assert all(data < DATA_FIM.isoformat() for data in ultima.values())


def test_inativos_nao_produzem_a_partir_da_saida(dados: Dados) -> None:
    inativos = [a for a in dados.animais if not a.ativo]
    assert len(inativos) == 5
    for animal in inativos:
        assert animal.data_saida is not None
        datas = [p.data for p in dados.producao if p.animal_id == animal.id]
        if datas:
            assert max(datas) < animal.data_saida
        partos = [p.data_parto for p in dados.partos if p.animal_id == animal.id]
        if partos:
            assert max(partos) <= animal.data_saida


def test_medias_por_vaca_ficam_entre_12_e_30_litros(dados: Dados) -> None:
    medias = medias_diarias(dados)
    assert all(12.0 <= m <= 30.0 for m in medias.values())


def test_media_do_rebanho_em_lactacao_fica_em_torno_de_20_litros(dados: Dados) -> None:
    medias = medias_diarias(dados)
    lactantes = [medias[a.id] for a in dados.animais if a.ativo and a.status == "lactacao"]
    assert 18.0 <= sum(lactantes) / len(lactantes) <= 24.0


def test_litros_tem_no_maximo_uma_casa_decimal(dados: Dados) -> None:
    assert all(round(p.litros_manha, 1) == p.litros_manha for p in dados.producao)
    assert all(round(p.litros_tarde, 1) == p.litros_tarde for p in dados.producao)


# --- vacas de baixa produção (resposta conhecida) ------------------------------------


@pytest.mark.parametrize("semente", range(40))
def test_quatro_vacas_de_baixa_producao_sao_as_quatro_piores_em_qualquer_semente(
    semente: int,
) -> None:
    dados = gerar_dados(semente)
    assert len(dados.baixa_producao_ids) == 4
    medias = medias_diarias(dados)
    lactantes = {a.id for a in dados.animais if a.ativo and a.status == "lactacao"}
    assert set(dados.baixa_producao_ids) <= lactantes
    # O gerador planeja de 12,2 a 13,2 L para as de baixa produção e no mínimo 15,5 L para as
    # demais. A média medida varia um pouco (ruído diário e arredondamento), mas as duas
    # faixas continuam separadas por pelo menos 1 L.
    assert all(medias[i] <= 14.0 for i in dados.baixa_producao_ids)
    outras = [medias[i] for i in lactantes - set(dados.baixa_producao_ids)]
    assert min(outras) >= 15.0
    quatro_piores = sorted(lactantes, key=lambda i: medias[i])[:4]
    assert set(quatro_piores) == set(dados.baixa_producao_ids)


# --- partos --------------------------------------------------------------------------


def test_toda_vaca_em_lactacao_tem_ao_menos_um_parto(dados: Dados) -> None:
    com_parto = {p.animal_id for p in dados.partos}
    assert all(a.id in com_parto for a in dados.animais if a.status == "lactacao")


def test_partos_sao_anteriores_a_primeira_producao_do_animal(dados: Dados) -> None:
    primeira = {}
    for p in dados.producao:
        primeira[p.animal_id] = min(p.data, primeira.get(p.animal_id, p.data))
    for parto in dados.partos:
        if parto.animal_id in primeira:
            assert parto.data_parto < primeira[parto.animal_id]


def test_animal_nasce_antes_do_primeiro_parto(dados: Dados) -> None:
    por_id = {a.id: a for a in dados.animais}
    for parto in dados.partos:
        assert por_id[parto.animal_id].data_nascimento < parto.data_parto


# --- condições do dia ----------------------------------------------------------------


def test_horarios_de_ordenha_sao_de_manha_e_de_tarde(dados: Dados) -> None:
    assert all(c.hora_ordenha_manha.startswith("05:") for c in dados.condicoes)
    assert all(c.hora_ordenha_tarde.startswith("15:") for c in dados.condicoes)


def test_ha_dias_com_e_sem_chuva(dados: Dados) -> None:
    chuvas = [c.chuva_manha + c.chuva_tarde for c in dados.condicoes]
    assert 0 in chuvas
    assert any(chuvas)


# --- gravação e linha de comando -----------------------------------------------------


def test_gerar_banco_recusa_sobrescrever_sem_pedir_e_mantem_o_arquivo_intacto(
    tmp_path: Path,
) -> None:
    caminho = tmp_path / "rebanho.db"
    gerar_banco(caminho)
    antes = caminho.read_bytes()
    with pytest.raises(FileExistsError):
        gerar_banco(caminho, semente=999)
    assert caminho.read_bytes() == antes


def test_forcar_nao_apaga_arquivo_que_nao_e_um_banco(tmp_path: Path) -> None:
    caminho = tmp_path / "anotacoes.txt"
    caminho.write_text("conteúdo importante", encoding="utf-8")
    with pytest.raises(FileExistsError, match="não é um banco SQLite"):
        gerar_banco(caminho, sobrescrever=True)
    assert caminho.read_text(encoding="utf-8") == "conteúdo importante"


def test_forcar_nao_apaga_pasta(tmp_path: Path) -> None:
    pasta = tmp_path / "rebanho.db"
    pasta.mkdir()
    (pasta / "arquivo.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError, match="não é um banco SQLite"):
        gerar_banco(pasta, sobrescrever=True)
    assert (pasta / "arquivo.txt").exists()


def test_gerar_banco_recria_quando_pedido(tmp_path: Path) -> None:
    caminho = tmp_path / "rebanho.db"
    gerar_banco(caminho, semente=1)
    dados = gerar_banco(caminho, semente=2, sobrescrever=True)
    leitura = abrir_somente_leitura(caminho)
    try:
        assert leitura.execute("SELECT COUNT(*) FROM producao_leite").fetchone()[0] == len(
            dados.producao
        )
    finally:
        leitura.close()


def test_banco_gerado_abre_em_somente_leitura(tmp_path: Path) -> None:
    caminho = tmp_path / "rebanho.db"
    gerar_banco(caminho)
    leitura = abrir_somente_leitura(caminho)
    try:
        assert leitura.execute("SELECT COUNT(*) FROM animais").fetchone()[0] == 60
        with pytest.raises(sqlite3.OperationalError):
            leitura.execute("DELETE FROM animais")
    finally:
        leitura.close()


def test_falha_na_gravacao_nao_deixa_banco_pela_metade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def falhar(conn: sqlite3.Connection, dados: Dados) -> None:
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(seed, "gravar_dados", falhar)
    caminho = tmp_path / "rebanho.db"
    with pytest.raises(RuntimeError):
        gerar_banco(caminho)
    assert not caminho.exists()


def test_linha_de_comando_cria_o_banco_e_recusa_sobrescrever_sem_forcar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    caminho = tmp_path / "rebanho.db"
    assert main(["--saida", str(caminho)]) == 0
    saida = capsys.readouterr().out
    assert "60 animais" in saida
    assert "2026-08-18 a 2026-11-15" in saida
    assert main(["--saida", str(caminho)]) == 1
    assert "--forcar" in capsys.readouterr().out
    assert main(["--saida", str(caminho), "--forcar"]) == 0


def test_linha_de_comando_com_forcar_recusa_arquivo_que_nao_e_banco(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    caminho = tmp_path / "anotacoes.txt"
    caminho.write_text("importante", encoding="utf-8")
    assert main(["--saida", str(caminho), "--forcar"]) == 1
    saida = capsys.readouterr().out
    assert "não é um banco SQLite" in saida
    assert "Rode de novo" not in saida  # a dica de --forcar não faz sentido aqui
    assert caminho.read_text(encoding="utf-8") == "importante"
