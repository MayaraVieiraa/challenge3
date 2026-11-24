"""Gera worker/evidencia/situacao_precedentes.json: a situação das súmulas, OJs e temas do TST para o validador v3.

O validador (alerta `precedente_cancelado`) precisa saber quais precedentes estão cancelados, suspensos ou
superados, mesmo quando eles não foram entregues como fonte (por exemplo, citados no texto de uma decisão antiga).
A base completa fica em dados/processed/precedentes/precedentes_tst.jsonl, que não é versionada; este catálogo
pequeno vai junto do código para funcionar em produção.

Lê:    dados/processed/precedentes/precedentes_tst.jsonl   (1.493 registros, JSONL)
Grava: worker/evidencia/situacao_precedentes.json           (JSON, versionado)
Execução: python avaliacao/scripts/gerar_catalogo_situacao_precedentes.py
"""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
ORIGEM = ROOT / 'dados/processed/precedentes/precedentes_tst.jsonl'
DESTINO = ROOT / 'worker/evidencia/situacao_precedentes.json'
SERIE_OJ = {'OJ-SDI1': 'SBDI-1', 'OJ-SDI2': 'SBDI-2', 'OJ-SDI1T': 'SBDI-1 (transitória)', 'OJ-SDC': 'SDC',
            'OJ-TP/OE': 'Tribunal Pleno/Órgão Especial'}
INATIVAS = {'cancelada', 'suspensa', 'tese_superada'}


def main():
    bruto = ORIGEM.read_bytes()
    registros = [json.loads(l) for l in bruto.decode('utf-8').splitlines() if l.strip()]
    sumulas, ojs, temas = {}, {}, {}
    for r in registros:
        num = str(r['numero'])
        situacao = r['situacao']
        if situacao not in INATIVAS and r.get('alerta_vigencia') and 'alcance: integral' in r['alerta_vigencia']:
            situacao = 'cancelamento_noticiado'     # quarentena: cancelamento integral noticiado em fonte não oficial
        if r['tipo'] == 'sumula' and situacao in INATIVAS | {'cancelamento_noticiado'}:
            sumulas[num] = situacao
        elif r['tipo'] == 'orientacao_jurisprudencial':
            ojs.setdefault(num, {})[SERIE_OJ[r['serie']]] = situacao   # todas: para saber se o número é ambíguo
        elif r['tipo'] == 'tema_repetitivo' and r['serie'] == 'IRR' and situacao in INATIVAS | {'cancelamento_noticiado'}:
            temas[num] = situacao
    catalogo = dict(
        descricao='Situação dos precedentes do TST para o validador v3 (alerta precedente_cancelado). '
                  'sumulas e temas_irr: só os inativos; ojs: todas, por número e série. cancelamento_noticiado = '
                  'quarentena (cancelamento integral noticiado em fonte não oficial).',
        origem='dados/processed/precedentes/precedentes_tst.jsonl', origem_sha256=hashlib.sha256(bruto).hexdigest(),
        registros=len(registros), sumulas=dict(sorted(sumulas.items(), key=lambda kv: int(kv[0]))),
        ojs=dict(sorted(ojs.items(), key=lambda kv: int(kv[0]))), temas_irr=dict(sorted(temas.items(), key=lambda kv: int(kv[0]))))
    DESTINO.write_text(json.dumps(catalogo, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    print(f'{DESTINO.relative_to(ROOT)}: {len(sumulas)} súmulas inativas, {len(ojs)} números de OJ, '
          f'{len(temas)} temas inativos')


if __name__ == '__main__':
    main()
