-- Esquema do banco do rebanho. Fonte da verdade: docs/spec.md, seção 4.
-- Regras que só envolvem uma tabela ficam aqui como CHECK/UNIQUE.
-- Regras que cruzam tabelas (datas de saída, parto de vaca em lactação) ficam no gerador
-- de dados e nos testes, porque um CHECK não consegue olhar outra tabela.
--
-- Todas as tabelas são STRICT: o SQLite recusa valor de tipo errado (por exemplo, o texto
-- 'abc' numa coluna REAL). Sem isso, o SQLite aceita qualquer tipo em qualquer coluna e um
-- CHECK como "litros >= 0" deixaria passar texto. Exige SQLite 3.37 ou mais novo.
--
-- Datas são texto ISO (AAAA-MM-DD) e horários são HH:MM. A expressão
-- COALESCE(date(x) = x, 0) rejeita texto que não seja uma data real (inclusive 2026-02-30):
-- date() devolve NULL para lixo, e o COALESCE transforma esse NULL em "falso", porque um
-- CHECK que dá NULL seria aceito.

CREATE TABLE animais (
    id              INTEGER PRIMARY KEY,
    -- Nome sem espaços nas pontas: "Mimosa" e "Mimosa " seriam dois nomes "iguais".
    nome            TEXT    NOT NULL CHECK (length(nome) > 0 AND nome = trim(nome)),
    sexo            TEXT    NOT NULL CHECK (sexo IN ('F', 'M')),
    raca            TEXT    NOT NULL CHECK (raca IN (
                        'gir', 'girolando_1_2', 'girolando_5_8', 'girolando_3_4',
                        'holandesa', 'tabapua', 'nelore', 'mestica')),
    data_nascimento TEXT    NOT NULL CHECK (COALESCE(date(data_nascimento) = data_nascimento, 0)),
    status          TEXT    NOT NULL CHECK (status IN ('lactacao', 'seca', 'novilha', 'corte')),
    lote            TEXT    NOT NULL CHECK (lote IN (
                        'alta_producao', 'media_producao', 'pre_parto', 'seca', 'recria',
                        'pasto', 'confinamento_inicial', 'confinamento_final')),
    ativo           INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    data_saida      TEXT    CHECK (data_saida IS NULL OR COALESCE(date(data_saida) = data_saida, 0)),
    motivo_saida    TEXT    CHECK (motivo_saida IS NULL
                                   OR motivo_saida IN ('morte', 'venda', 'abate', 'outro')),

    -- Só animal de corte pode ser macho.
    CHECK (sexo = 'F' OR status = 'corte'),

    -- Combinações válidas de status e lote.
    CHECK (
        (status = 'lactacao' AND lote IN ('alta_producao', 'media_producao'))
        OR (status = 'seca'    AND lote IN ('pre_parto', 'seca', 'pasto'))
        OR (status = 'novilha' AND lote IN ('recria', 'pasto'))
        OR (status = 'corte'   AND lote IN ('pasto', 'confinamento_inicial',
                                            'confinamento_final'))
    ),

    -- Exclusão lógica: ativo não tem saída; inativo tem data e motivo.
    CHECK (
        (ativo = 1 AND data_saida IS NULL AND motivo_saida IS NULL)
        OR (ativo = 0 AND data_saida IS NOT NULL AND motivo_saida IS NOT NULL)
    ),

    -- Ninguém sai da fazenda antes de nascer.
    CHECK (data_saida IS NULL OR data_saida >= data_nascimento)
) STRICT;

-- Nome único só entre animais ativos. É um índice único parcial: vale apenas para as linhas
-- com ativo = 1. COLLATE NOCASE ignora maiúsculas e minúsculas só em letras ASCII: "Áurea" e
-- "áurea" (com acento) seriam aceitos como nomes diferentes. A busca por nome nas ferramentas
-- ignora acentos, então o gerador deve evitar nomes que só diferem por acento.
CREATE UNIQUE INDEX idx_animais_nome_ativo ON animais (nome COLLATE NOCASE) WHERE ativo = 1;

CREATE TABLE producao_leite (
    id           INTEGER PRIMARY KEY,
    animal_id    INTEGER NOT NULL REFERENCES animais (id),
    data         TEXT    NOT NULL CHECK (COALESCE(date(data) = data, 0)),
    litros_manha REAL    NOT NULL CHECK (litros_manha >= 0),
    litros_tarde REAL    NOT NULL CHECK (litros_tarde >= 0),
    -- O UNIQUE já cria o índice (animal_id, data) que acelera a busca por animal e período.
    UNIQUE (animal_id, data)
) STRICT;

-- Acelera a busca da data de referência (maior data) e as consultas do rebanho por período.
CREATE INDEX idx_producao_data ON producao_leite (data);

CREATE TABLE condicoes_dia (
    data               TEXT    PRIMARY KEY CHECK (COALESCE(date(data) = data, 0)),
    hora_ordenha_manha TEXT    NOT NULL CHECK (COALESCE(strftime('%H:%M', hora_ordenha_manha) = hora_ordenha_manha, 0)),
    hora_ordenha_tarde TEXT    NOT NULL CHECK (COALESCE(strftime('%H:%M', hora_ordenha_tarde) = hora_ordenha_tarde, 0)),
    chuva_manha        INTEGER NOT NULL CHECK (chuva_manha IN (0, 1)),
    chuva_tarde        INTEGER NOT NULL CHECK (chuva_tarde IN (0, 1)),
    temp_min_c         REAL    NOT NULL,
    temp_max_c         REAL    NOT NULL,
    CHECK (temp_min_c <= temp_max_c)
) STRICT;

CREATE TABLE partos (
    id         INTEGER PRIMARY KEY,
    animal_id  INTEGER NOT NULL REFERENCES animais (id),
    data_parto TEXT    NOT NULL CHECK (COALESCE(date(data_parto) = data_parto, 0)),
    UNIQUE (animal_id, data_parto)
) STRICT;
