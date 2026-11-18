"""Monta a planilha de revisão humana do juiz Gemma 3 27B (camadas 1 e 3 da revisão).

Camada 1 (automática, sem LLM): `src/integracao/revisao.py` confere, nas fontes entregues ao gerador, as afirmações que
o juiz não considerou apoiadas e as referências jurídicas de todas as afirmações, e faz a triagem das respostas.

Camada 3 (pessoa): planilha com as abas
  leia_primeiro         instruções
  rotulo_cego           amostra sorteada (aprovadas e reprovadas pela regra), sem nada do juiz: preencher PRIMEIRO
  reprovadas            as respostas reprovadas pela regra, com motivos e triagem: concorda com a reprovação?
  afirmacoes            uma linha por afirmação a conferir, com o trecho mais parecido da fonte: o juiz acertou?
  aprovadas_com_alerta  aprovadas pela regra, mas com artigo, lei ou número que não está em fonte nenhuma
  fontes                texto das fontes entregues, por resposta

Entradas (fora do Git): output/kaggle/juiz_27b/dataset/pedidos.jsonl e output/kaggle/juiz_27b/julgamentos.jsonl
(scripts/importar_juiz_kaggle.py --27b). Com --llama, usa output/kaggle/juiz_27b_llama/.
Saídas:
  output/integracao/revisao_juiz/revisao_juiz_27b[_llama].xlsx   (fora do Git: tem perguntas e trechos protegidos)
  reports/integracao/juiz/triagem_27b[_llama].csv                (só identificadores, notas, motivos e contagens)
"""
from pathlib import Path
import json
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from src.integracao import revisao

SEMENTE = 42
AMOSTRA_APROVADAS, AMOSTRA_REPROVADAS = 15, 10   # proporção próxima da observada (67 × 44 no Qwen)
ORDEM_TRIAGEM = ['provavel_falso_alarme', 'inconclusiva', 'provavel_reprovacao_correta', 'revisar_notas']
SINAIS_ALERTA = ('referencia_ausente',)

LEIA = """Revisão do juiz Gemma 3 27B — como preencher

Objetivo: saber se o juiz acerta. Por isso a sua opinião precisa ser independente da dele.

1. Comece pela aba rotulo_cego, ANTES de abrir as outras. Ela traz uma amostra sorteada de respostas, aprovadas e
   reprovadas pelo juiz, sem nenhuma informação do juiz. Para cada uma, leia a pergunta, a resposta e as fontes
   (aba fontes, filtrando pelo id) e escolha aprovada ou reprovada na coluna seu_veredito. Use o mesmo critério do
   juiz: reprovar se a resposta afirma algo que as fontes não sustentam, erra o direito, ou não segue a ação esperada
   (responder = explicar com fontes; orientar_sem_aconselhar = regra geral + encaminhamento, sem dizer o que fazer).
2. Depois, aba reprovadas: o juiz reprovou essas respostas. A coluna triagem é a checagem automática:
     provavel_falso_alarme        as afirmações que o juiz não aceitou parecem estar no texto das fontes
     inconclusiva                 a checagem não conseguiu decidir
     provavel_reprovacao_correta  há artigo, número ou trecho que não aparece nas fontes
     revisar_notas                o juiz deu nota baixa em correção ou comportamento: a checagem não avalia isso
   Marque concorda_com_reprovacao (sim / não / em parte). Comece pelas de falso alarme: são as mais prováveis de
   estarem erradas.
3. Aba afirmacoes: cada afirmação que o juiz não aceitou, com o trecho mais parecido da fonte. Marque juiz_certo.
   A checagem só olha palavras e números: uma negação ou um prazo trocado passam despercebidos.
4. Aba aprovadas_com_alerta: o juiz aprovou, mas a resposta cita artigo, lei ou número que não está em fonte nenhuma.
   Marque deveria_reprovar (sim / não).

Não altere as colunas que já vêm preenchidas. Ao terminar, salve com o mesmo nome e avise.
"""


def carregar(base):
    pedidos = {json.loads(l)['pergunta_id']: json.loads(l)
               for l in (base / 'dataset/pedidos.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()}
    julgamentos = [json.loads(l) for l in (base / 'julgamentos.jsonl').read_text(encoding='utf-8').splitlines()
                   if l.strip()]
    return pedidos, julgamentos


def notas(j):
    return ' · '.join(f'{c[:4]} {j.get(c) if j.get(c) is not None else "–"}'
                      for c in ('fidelidade', 'correcao', 'comportamento', 'clareza'))


def montar(pedidos, julgamentos, prefixo):
    linhas, afirmacoes, alertas, fontes = [], [], [], []
    for j in julgamentos:
        if not j['julgamento_id'].startswith(prefixo) or not j.get('valido'):
            continue
        rid = j['julgamento_id'].removeprefix(prefixo)
        e = revisao.separar_entrada(pedidos[j['julgamento_id']]['mensagens'][1]['content'])
        t = revisao.triar(j, e['fontes'])
        reprovada = j['veredito_regra'] == 'reprovada'
        for f in e['fontes']:
            fontes.append(dict(id=rid, fonte=f['n'], rotulo=f['rotulo'], texto=f['texto']))
        # referências ausentes também nas afirmações que o juiz aceitou (erro do juiz no sentido contrário)
        alerta = []
        for i, a in enumerate(j.get('afirmacoes') or [], 1):
            c = revisao.checar_afirmacao(a, e['fontes'])
            if reprovada and a.get('suporte') in revisao.NAO_APOIADAS:
                afirmacoes.append(dict(id=rid, n=i, triagem_resposta=t['triagem'], afirmacao=a.get('texto'),
                                       suporte_juiz=a.get('suporte'),
                                       fonte_citada=', '.join(map(str, revisao.numeros_fonte(a.get('fonte')))),
                                       sinal_checagem=c['sinal'], referencias_ausentes=c['referencias_ausentes'],
                                       cobertura=c['cobertura_melhor'], fonte_do_trecho=c['fonte_trecho'],
                                       trecho_mais_parecido=c['trecho'], juiz_certo='', observacao=''))
            if c['sinal'] in SINAIS_ALERTA:
                alerta.append((i, a, c))
        if not reprovada and alerta:
            alertas.append(dict(id=rid, acao=e['acao'], notas=notas(j), pergunta=e['pergunta'],
                                afirmacoes_com_alerta='\n\n'.join(
                                    f'({i}) {a.get("texto")}\n   ausente nas fontes: {c["referencias_ausentes"]}'
                                    for i, a, c in alerta),
                                resposta=e['resposta'], deveria_reprovar='', observacao=''))
        sinais = pd.Series([c['sinal'] for c in t['checagens']], dtype=object).value_counts().to_dict()
        linhas.append(dict(id=rid, acao=e['acao'], veredito_regra=j['veredito_regra'], veredito_modelo=j['veredito'],
                           triagem=t['triagem'] if reprovada else '', motivos=t['motivos'] if reprovada else '',
                           notas=notas(j), justificativa_juiz=j.get('justificativa') or '',
                           afirmacoes_a_conferir=len(t['checagens']) if reprovada else 0,
                           **{f'sinal_{s}': sinais.get(s, 0) if reprovada else 0
                              for s in ('apoio_textual', 'inconclusivo', 'pouco_apoio', 'referencia_ausente')},
                           alertas_em_aprovada=len(alerta) if not reprovada else 0,
                           pergunta=e['pergunta'], resposta=e['resposta'], referencia=e['referencia'] or '',
                           fontes_rotulos='\n'.join(f'[{f["n"]}] {f["rotulo"]}' for f in e['fontes'])))
    return pd.DataFrame(linhas), pd.DataFrame(afirmacoes), pd.DataFrame(alertas), pd.DataFrame(fontes)


def sortear_cego(tabela):
    rng = random.Random(SEMENTE)
    aprov = sorted(tabela.loc[tabela.veredito_regra == 'aprovada', 'id'])
    reprov = sorted(tabela.loc[tabela.veredito_regra == 'reprovada', 'id'])
    ids = rng.sample(aprov, min(AMOSTRA_APROVADAS, len(aprov))) + rng.sample(reprov, min(AMOSTRA_REPROVADAS, len(reprov)))
    rng.shuffle(ids)
    cego = tabela.set_index('id').loc[ids, ['acao', 'pergunta', 'resposta', 'referencia', 'fontes_rotulos']].reset_index()
    cego.insert(0, 'ordem', range(1, len(cego) + 1))
    return cego.assign(seu_veredito='', motivo='')


LARGURAS = dict(ordem=7, id=22, n=5, acao=14, pergunta=45, resposta=80, referencia=50, fontes_rotulos=40, triagem=24,
                motivos=36, notas=26, justificativa_juiz=50, afirmacao=60, trecho_mais_parecido=60, rotulo=50,
                texto=110, afirmacoes_com_alerta=60, observacao=30, motivo=30)
PREENCHER = {'seu_veredito': '"aprovada,reprovada"', 'concorda_com_reprovacao': '"sim,não,em parte"',
             'juiz_certo': '"sim,não,em parte"', 'deveria_reprovar': '"sim,não"'}


def formatar(ws, df):
    cabecalho = Font(bold=True)
    amarelo = PatternFill('solid', fgColor='FFF2CC')
    for i, col in enumerate(df.columns, 1):
        letra = ws.cell(row=1, column=i).column_letter
        ws.column_dimensions[letra].width = LARGURAS.get(col, 14)
        ws.cell(row=1, column=i).font = cabecalho
        editavel = col in PREENCHER or col in ('observacao', 'motivo')
        for r in range(2, len(df) + 2):
            celula = ws.cell(row=r, column=i)
            celula.alignment = Alignment(wrap_text=True, vertical='top')
            if editavel:
                celula.fill = amarelo
        if col in PREENCHER and len(df):
            dv = DataValidation(type='list', formula1=PREENCHER[col], allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f'{letra}2:{letra}{len(df) + 1}')
    ws.freeze_panes = 'C2'
    ws.auto_filter.ref = ws.dimensions


def main():
    llama = '--llama' in sys.argv
    sufixo = '_27b_llama' if llama else '_27b'
    base = ROOT / f'output/kaggle/juiz{sufixo}'
    pedidos, julgamentos = carregar(base)
    tabela, afirmacoes, alertas, fontes = montar(pedidos, julgamentos, 'llama_' if llama else 'ger_')

    reprovadas = tabela[tabela.veredito_regra == 'reprovada'].copy()
    reprovadas['_ordem'] = reprovadas.triagem.map({t: i for i, t in enumerate(ORDEM_TRIAGEM)})
    reprovadas = reprovadas.sort_values(['_ordem', 'id']).drop(columns='_ordem')
    reprovadas = reprovadas[['id', 'triagem', 'motivos', 'notas', 'justificativa_juiz', 'acao', 'pergunta', 'resposta',
                             'referencia', 'fontes_rotulos']].assign(concorda_com_reprovacao='', observacao='')
    if len(afirmacoes):
        afirmacoes['_ordem'] = afirmacoes.triagem_resposta.map({t: i for i, t in enumerate(ORDEM_TRIAGEM)})
        afirmacoes = afirmacoes.sort_values(['_ordem', 'id', 'n']).drop(columns='_ordem')
    cego = sortear_cego(tabela)

    destino = ROOT / 'output/integracao/revisao_juiz'
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f'revisao_juiz{sufixo}.xlsx'
    abas = dict(rotulo_cego=cego, reprovadas=reprovadas, afirmacoes=afirmacoes, aprovadas_com_alerta=alertas,
                fontes=fontes)
    with pd.ExcelWriter(arquivo, engine='openpyxl') as w:
        pd.DataFrame({'instruções': LEIA.splitlines()}).to_excel(w, sheet_name='leia_primeiro', index=False)
        w.sheets['leia_primeiro'].column_dimensions['A'].width = 120
        for nome, df in abas.items():
            df.to_excel(w, sheet_name=nome, index=False)
            formatar(w.sheets[nome], df)

    colunas_csv = ['id', 'acao', 'veredito_regra', 'veredito_modelo', 'triagem', 'motivos', 'notas',
                   'afirmacoes_a_conferir', 'sinal_apoio_textual', 'sinal_inconclusivo', 'sinal_pouco_apoio',
                   'sinal_referencia_ausente', 'alertas_em_aprovada']
    csv = ROOT / f'reports/integracao/juiz/triagem{sufixo}.csv'
    tabela[colunas_csv].assign(no_rotulo_cego=tabela.id.isin(cego.id)).to_csv(csv, index=False, encoding='utf-8')

    print(f'respostas: {len(tabela)} | reprovadas pela regra: {len(reprovadas)}')
    print('triagem das reprovadas:', reprovadas.triagem.value_counts().reindex(ORDEM_TRIAGEM, fill_value=0).to_dict())
    if len(afirmacoes):
        print('afirmações a conferir:', len(afirmacoes), afirmacoes.sinal_checagem.value_counts().to_dict())
    print('aprovadas com alerta:', len(alertas))
    print('rótulo cego:', len(cego), '(', (tabela.set_index('id').loc[cego.id].veredito_regra == 'aprovada').sum(),
          'aprovadas pela regra )')
    print('planilha:', arquivo)
    print('triagem :', csv.relative_to(ROOT))


if __name__ == '__main__':
    main()
