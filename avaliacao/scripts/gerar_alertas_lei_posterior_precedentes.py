"""Alertas de lei posterior: súmulas e OJs do TST anteriores a uma mudança da lei sobre o mesmo ponto.

Princípio (decisão da usuária, 2026-11-23): quando a lei ou a Constituição muda depois do precedente, sobre o mesmo
ponto, vale a lei nova para os fatos posteriores à vigência dela. A súmula é a leitura da lei da época.

Todas as súmulas e OJs da base são anteriores à Lei 13.467/2017 (Reforma Trabalhista, em vigor desde 11/11/2017):
a data mais recente nos textos é de 30/06/2017. E todas são anteriores à EC 141/2026.

Três critérios:
  automatico_dispositivo  o enunciado cita um parágrafo ou o caput de artigo da CLT que a CLT da base marca como
                          "Redação dada", "Incluído" ou "Revogado" pela Lei nº 13.467/2017   -> alerta entregue
  lista_manual            conflitos conhecidos com a Reforma ou com a EC 141, com o dispositivo indicado à mão
                                                                                              -> alerta entregue
  automatico_artigo       cita só o artigo (sem parágrafo), e algum dispositivo dele foi alterado
                                                                                              -> só para revisão
Súmulas e OJs em quarentena (cancelamento integral noticiado) ou canceladas não são entregues ao modelo; aparecem na
lista de revisão só para conferência.

TODA A LISTA DEVE SER CONFIRMADA PELO ADVOGADO REVISOR (campo confirmado_advogado).

Lê:    dados/processed/precedentes/precedentes_tst.jsonl        (1.493 registros, JSONL; fora do Git)
       dados/raw/legislacao/codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md
Grava: worker/evidencia/precedentes_lei_posterior.json            (JSON versionado; usado na entrega e no validador)
       dados/relatorios/precedentes/lei_posterior/lista_para_revisao_advogado.csv   (CSV para o advogado revisor)
Uso:   python avaliacao/scripts/gerar_alertas_lei_posterior_precedentes.py
"""
from pathlib import Path
import csv
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
ORIGEM = ROOT / 'dados/processed/precedentes/precedentes_tst.jsonl'
CLT = ROOT / 'dados/raw/legislacao/codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md'
DESTINO = ROOT / 'worker/evidencia/precedentes_lei_posterior.json'
REVISAO = ROOT / 'dados/relatorios/precedentes/lei_posterior/lista_para_revisao_advogado.csv'

REFORMA = dict(lei='Lei 13.467/2017 (Reforma Trabalhista)', vigencia='2017-11-11')
EC141 = dict(lei='Emenda Constitucional 141/2026', vigencia='2026-12-16')

# (id, mudança, dispositivos alterados, motivo). Dispositivos da CLT são conferidos contra as marcas da CLT da base.
MANUAL = [
    ('TST-SUM-6', REFORMA, [('CLT', '461', None)], 'equiparação salarial: o art. 461 foi reescrito (tempo na função, '
     'mesmo estabelecimento, quadro de carreira sem homologação)'),
    ('TST-SUM-85', REFORMA, [('CLT', '59', '§5'), ('CLT', '59', '§6'), ('CLT', '59-B', None)],
     'compensação de jornada: banco de horas por acordo individual e compensação mensal tácita'),
    ('TST-SUM-101', REFORMA, [('CLT', '457', '§2')], 'diárias para viagem deixaram de integrar a remuneração'),
    ('TST-SUM-241', REFORMA, [('CLT', '457', '§2')],
     'auxílio-alimentação, vedado o pagamento em dinheiro, deixou de integrar a remuneração'),
    ('TST-SUM-219', REFORMA, [('CLT', '791-A', None)], 'honorários advocatícios de sucumbência na Justiça do Trabalho'),
    ('TST-SUM-329', REFORMA, [('CLT', '791-A', None)], 'honorários advocatícios de sucumbência na Justiça do Trabalho'),
    ('TST-SUM-372', REFORMA, [('CLT', '468', '§2')],
     'a reversão ao cargo efetivo não assegura a manutenção da gratificação de função, independentemente do tempo'),
    ('TST-SUM-463', REFORMA, [('CLT', '790', '§3'), ('CLT', '790', '§4')],
     'justiça gratuita: limite de renda e comprovação da insuficiência de recursos'),
    ('TST-SUM-331', REFORMA, [('Lei 6.019/1974', '4º-A', None), ('Lei 6.019/1974', '5º-A', None)],
     'terceirização de quaisquer atividades, inclusive a principal; o STF também a admitiu (ADPF 324 e Tema 725 '
     'de repercussão geral)'),
    ('TST-SUM-110', EC141, [('CF', '7º', 'XV')],
     'pressupõe o repouso semanal de 24 horas; a partir de 16/12/2026, o repouso semanal é de 2 dias'),
    ('TST-OJ-SDI1-410', EC141, [('CF', '7º', 'XV')],
     'trata do repouso concedido após o sétimo dia de trabalho; a partir de 16/12/2026, o repouso semanal é de 2 dias'),
]

CITACAO_CLT = re.compile(r'\bart(?:igo)?s?\.?\s*(?P<art>\d+(?:-[A-Z])?)\s*[ºo°]?(?P<disp>(?:\s*,\s*(?:§\s*\d+\s*[ºo°]?|caput|'
                         r'par[áa]grafo\s+[úu]nico|[IVXL]+(?![a-z])))*)[^.;\n\[]{0,30}?\bCLT\b', re.IGNORECASE)


def alteracoes_clt():
    """{artigo: {dispositivo}} marcados pela Lei 13.467/2017 na CLT da base ('caput', '§2', 'unico')."""
    alterados, art, disp = {}, None, 'caput'
    for linha in CLT.read_text(encoding='utf-8').splitlines():
        m = re.match(r'\s*#*\s*Art\.\s*(\d+(?:-[A-Z])?)', linha)
        if m:
            art, disp = m.group(1).upper(), 'caput'
            continue
        mp = re.match(r'\s*§\s*(\d+)', linha)
        if mp:
            disp = f'§{mp.group(1)}'
        elif re.match(r'\s*Parágrafo único', linha, re.IGNORECASE):
            disp = 'unico'
        if art and re.search(r'pela Lei n[ºo°]\s*13\.467', linha):
            alterados.setdefault(art, set()).add(disp)
    return alterados


def citacoes(texto):
    """[(artigo, {dispositivos} ou None)] dos artigos da CLT citados no enunciado."""
    saida = []
    for m in CITACAO_CLT.finditer(texto):
        d = set()
        for x in re.findall(r'§\s*(\d+)|(caput)|(par[áa]grafo\s+[úu]nico)', m.group('disp') or '', re.IGNORECASE):
            d.add(f'§{x[0]}' if x[0] else 'caput' if x[1] else 'unico')
        saida.append((m.group('art').upper(), d or None))
    return saida


def nome_disp(art, disp, codigo='CLT'):
    if disp is None:
        return f'art. {art} da {codigo}' if codigo == 'CLT' else f'art. {art} da {codigo}'
    if disp.startswith('§'):
        return f'art. {art}, § {disp[1:]}º, da {codigo}'
    return f'art. {art}, {"parágrafo único" if disp == "unico" else disp}, da {codigo}'


def texto_alerta(mudanca, dispositivos, motivo):
    data = '11/11/2017' if mudanca is REFORMA else '16/12/2026'
    lista = ', '.join(dispositivos)
    base = (f'enunciado anterior à {mudanca["lei"]}, em vigor desde {data}, que alterou {lista}' if mudanca is REFORMA
            else f'enunciado anterior à {mudanca["lei"]} ({lista}), com efeito a partir de {data}')
    return f'{base}{": " + motivo if motivo else ""}. Para fatos a partir de {data}, vale a regra nova no que contrariar o enunciado.'


def main():
    bruto = ORIGEM.read_bytes()
    registros = {r['id']: r for r in (json.loads(l) for l in bruto.decode('utf-8').splitlines() if l.strip())}
    alterados = alteracoes_clt()
    entregues, revisao = {}, []

    for rid, mudanca, disps, motivo in MANUAL:
        r = registros[rid]
        for codigo, art, disp in disps:
            if codigo == 'CLT' and (art not in alterados or (disp and disp not in alterados[art])):
                sys.exit(f'{rid}: {nome_disp(art, disp)} não está marcado pela Lei 13.467 na CLT da base')
        nomes = [nome_disp(a, d, c) if c == 'CLT' else (f'art. {a}, {d}, da CF' if c == 'CF' else f'art. {a} da {c}')
                 for c, a, d in disps]
        entregues[rid] = dict(origem='lista_manual', lei=mudanca['lei'], vigencia_mudanca=mudanca['vigencia'],
                              dispositivos=nomes, motivo=motivo, alerta=texto_alerta(mudanca, nomes, motivo),
                              confirmado_advogado=False)

    for rid, r in registros.items():
        if r['tipo'] == 'tema_repetitivo' or rid in entregues:
            continue
        por_disp, por_art = [], []
        for art, disps in citacoes(r['texto']):
            if art not in alterados:
                continue
            if disps is None:
                por_art.append(nome_disp(art, None))
            else:
                por_disp += [nome_disp(art, d) for d in sorted(disps & alterados[art])]
        por_disp, por_art = sorted(set(por_disp)), sorted(set(por_art))
        if not (por_disp or por_art):
            continue
        ativo = r['buscavel'] and r['situacao'] in ('vigente', 'suspensa')
        if por_disp and ativo:
            entregues[rid] = dict(origem='automatico_dispositivo', lei=REFORMA['lei'], vigencia_mudanca=REFORMA['vigencia'],
                                  dispositivos=por_disp, motivo=None, alerta=texto_alerta(REFORMA, por_disp, None),
                                  confirmado_advogado=False)
        else:
            revisao.append(dict(id=rid, nome_citacao=r['nome_citacao'], situacao=r['situacao'], buscavel=r['buscavel'],
                                titulo=r['titulo'], criterio='automatico_dispositivo' if por_disp else 'automatico_artigo',
                                dispositivos='; '.join(por_disp or por_art), entregue_ao_modelo=False, motivo='',
                                observacao=('fora da busca (cancelado ou em quarentena)' if not ativo
                                            else 'cita só o artigo; alerta não entregue até confirmação')))

    for rid, e in entregues.items():
        r = registros[rid]
        revisao.append(dict(id=rid, nome_citacao=r['nome_citacao'], situacao=r['situacao'], buscavel=r['buscavel'],
                            titulo=r['titulo'], criterio=e['origem'], dispositivos='; '.join(e['dispositivos']),
                            entregue_ao_modelo=r['buscavel'], motivo=e['motivo'] or '',
                            observacao='' if r['buscavel'] else 'fora da busca (cancelado ou em quarentena)'))
    # quarentena com tema da Reforma: só para conferência (o modelo não recebe; o validador avisa se ele citar)
    for rid in ('TST-SUM-90', 'TST-SUM-320', 'TST-SUM-437', 'TST-SUM-444', 'TST-SUM-366', 'TST-SUM-429', 'TST-SUM-449',
                'TST-SUM-114', 'TST-SUM-268', 'TST-SUM-294'):
        if rid not in {l['id'] for l in revisao}:
            r = registros[rid]
            revisao.append(dict(id=rid, nome_citacao=r['nome_citacao'], situacao=r['situacao'], buscavel=r['buscavel'],
                                titulo=r['titulo'], criterio='quarentena', dispositivos='', entregue_ao_modelo=False,
                                motivo='tema alterado pela Reforma', observacao=r.get('alerta_vigencia') or ''))

    entregues = {k: v for k, v in entregues.items() if registros[k]['buscavel']}
    catalogo = dict(descricao='Precedentes do TST anteriores a uma mudança da lei sobre o mesmo ponto (alerta de lei '
                              'posterior). Entregue junto do precedente e conferido pelo validador v3. A confirmar '
                              'pelo advogado revisor.',
                    origem='dados/processed/precedentes/precedentes_tst.jsonl', origem_sha256=hashlib.sha256(bruto).hexdigest(),
                    clt_sha256=hashlib.sha256(CLT.read_bytes()).hexdigest(), precedentes=dict(sorted(entregues.items())))
    DESTINO.write_text(json.dumps(catalogo, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    REVISAO.parent.mkdir(parents=True, exist_ok=True)
    ordem = {'lista_manual': 0, 'automatico_dispositivo': 1, 'automatico_artigo': 2, 'quarentena': 3}
    revisao.sort(key=lambda l: (ordem[l['criterio']], l['id']))
    with REVISAO.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(revisao[0]) + ['confirmado_advogado', 'comentario_advogado'])
        w.writeheader()
        for l in revisao:
            w.writerow(dict(l, confirmado_advogado='', comentario_advogado=''))
    from collections import Counter
    print(f'{DESTINO.relative_to(ROOT)}: {len(entregues)} precedentes com alerta entregue ao modelo',
          dict(Counter(e['origem'] for e in entregues.values())))
    print(f'{REVISAO.relative_to(ROOT)}: {len(revisao)} linhas', dict(Counter(l['criterio'] for l in revisao)))


if __name__ == '__main__':
    main()
