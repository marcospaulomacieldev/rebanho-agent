"""Relatório das evals: texto para o terminal e arquivo JSON."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from evals.executor import Rodada

VERSAO_DO_FORMATO = 1
_ROTULOS = {
    "ferramenta": "Ferramenta correta",
    "argumentos_equivalentes": "Argumentos equivalentes",
    "argumentos_identicos": "Argumentos idênticos",
    "numeros": "Números corretos na resposta",
    "fidelidade": "Fidelidade numérica",
    "comportamento": "Comportamento (recusa, pergunta de volta)",
    "execucao_aprovada": "Execução aprovada (tudo junto)",
    "consistencia_entre_variantes": "Consistência entre variantes (casos)",
}
# Métricas com meta de 90% na spec (seção 6), usadas por `--exigir`.
METRICAS_DA_SPEC = ("ferramenta", "numeros", "consistencia_entre_variantes")


def _fracao(taxa: dict[str, Any]) -> str:
    if not taxa["total"]:
        return "não medido"
    percentual = f"{100 * taxa['taxa']:.1f}".replace(".", ",")
    return f"{taxa['acertos']}/{taxa['total']} ({percentual}%)"


def _segundos(valor: float | None) -> str:
    return "não medido" if valor is None else f"{valor:.1f} s".replace(".", ",")


def montar(metadados: dict[str, Any], resumo: dict[str, Any], rodada: Rodada) -> dict[str, Any]:
    """Relatório completo, pronto para virar JSON."""
    return {
        "versao_do_formato": VERSAO_DO_FORMATO,
        "metadados": metadados,
        "resumo": resumo,
        "execucoes": [asdict(e) for e in rodada.execucoes],
    }


def gravar(relatorio: dict[str, Any], pasta: Path, nome: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / nome
    caminho.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def formatar(relatorio: dict[str, Any]) -> str:
    """Resumo em texto: métricas, uma linha por caso e as falhas."""
    meta, resumo = relatorio["metadados"], relatorio["resumo"]
    linhas = [
        "== Evals do agente ==",
        f"Modelo: {meta.get('modelo')} | repetições por pergunta: {meta.get('repeticoes')}"
        f" | commit: {meta.get('commit') or 'desconhecido'}"
        + (" (com mudanças não commitadas)" if meta.get("arvore_suja") else ""),
        f"Execuções válidas: {resumo['execucoes_validas']}"
        f" | não executadas (falha de infraestrutura): {resumo['execucoes_nao_executadas']}",
    ]
    if resumo["interrompida"]:
        linhas.append(f"RODADA INTERROMPIDA: {resumo['interrompida']}")
    if resumo["amostra_pequena"]:
        linhas.append(
            "Atenção: amostra pequena (menos de 30 execuções). As taxas abaixo são indícios."
        )
    linhas.append("")
    linhas.extend(
        f"  {rotulo:<44} {_fracao(resumo['metricas'][nome])}" for nome, rotulo in _ROTULOS.items()
    )
    linhas.append(
        f"  Latência do modelo por pergunta: mediana {_segundos(resumo['latencia_mediana_s'])},"
        f" percentil 90 {_segundos(resumo['latencia_p90_s'])}"
    )
    linhas.append(
        f"  Chamadas ao modelo: {meta.get('chamadas_ao_modelo')}"
        f" | novas tentativas: {meta.get('novas_tentativas')}"
        f" | passos por pergunta (média): {str(resumo['passos_medios']).replace('.', ',')}"
        f" | chamadas de ferramenta além das esperadas: {resumo['chamadas_a_mais']}"
    )
    linhas += ["", "Por caso (execuções aprovadas):"]
    linhas.extend(
        f"  {caso['id']:<34} {caso['aprovadas']}/{caso['total']}"
        + (f"  ({caso['variantes']} variantes)" if caso["variantes"] > 1 else "")
        for caso in resumo["casos"]
    )

    falhas = [e for e in relatorio["execucoes"] if e["executada"] and not e["passou"]]
    if falhas:
        linhas += ["", "Falhas:"]
    for e in falhas:
        reprovadas = [nome for nome, valor in e["checagens"].items() if valor is False]
        chamadas = ", ".join(f"{c['ferramenta']}({c['argumentos']})" for c in e["chamadas"])
        motivo = e["erro"] or ", ".join(reprovadas) or "resposta incompleta"
        linhas += [
            f"- {e['caso_id']} (variante {e['variante']}, repetição {e['repeticao']}):"
            f" {e['pergunta']}",
            f"    reprovou em: {motivo}",
        ]
        if e["caso_id"] in resumo["esperado"]:
            esperadas = ", ".join(
                f"{c['ferramenta']}({c['argumentos']})" for c in resumo["esperado"][e["caso_id"]]
            )
            linhas.append(f"    esperado: {esperadas or 'nenhuma chamada'}")
        linhas += [
            f"    chamadas: {chamadas or 'nenhuma'}",
            f"    resposta: {(e['resposta'] or '').strip()[:300]}",
        ]
    nao_executadas = [e for e in relatorio["execucoes"] if not e["executada"]]
    if nao_executadas:
        linhas += ["", "Não executadas:"]
        linhas.extend(f"- {e['caso_id']}: {e['erro']}" for e in nao_executadas)
    return "\n".join(linhas)


def abaixo_do_exigido(resumo: dict[str, Any], minimo: float) -> list[str]:
    """Rótulos das métricas da spec abaixo do mínimo, ou que não foram medidas."""
    reprovadas = []
    for nome in METRICAS_DA_SPEC:
        taxa = resumo["metricas"][nome]
        if not taxa["total"] or taxa["taxa"] < minimo:
            reprovadas.append(_ROTULOS[nome])
    return reprovadas
