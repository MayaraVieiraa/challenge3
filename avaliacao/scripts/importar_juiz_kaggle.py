"""Baixa os julgamentos do Gemma 3 12B (Kaggle), valida o JSON e cruza com as decisões humanas e os guardrails.

Saídas:
  dados/output/kaggle/juiz_v2/julgamentos.jsonl            julgamentos completos (fora do Git)
  dados/relatorios/integracao/juiz_v2/calibracao.csv          juiz × revisora nas 9 respostas com decisão humana
  dados/relatorios/integracao/juiz_v2/julgamentos.csv         notas e veredito por resposta gerada, com o resultado dos guardrails
  dados/relatorios/integracao/juiz_v2/julgamentos_llama.csv   (com --llama) notas e veredito das respostas da LLM B
Uso: python avaliacao/scripts/importar_juiz_kaggle.py [--sem-download] [--llama] [--27b]  (--27b: juiz Gemma 3 27B, arquivos com sufixo _27b)
"""
from pathlib import Path
import glob
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pandas as pd

from avaliacao.juiz import interpretar
from worker.evidencia.observabilidade import Observabilidade

KERNEL = 'laisapaiva93/lexia-juiz-gemma3-v2'
BASE = ROOT / 'dados/output/kaggle/juiz_v2'
RELATORIOS = ROOT / 'dados/relatorios/integracao/juiz_v2'


def main():
    global KERNEL, BASE
    llama = '--llama' in sys.argv   # julgamentos das respostas da LLM B (preparar_juiz_kaggle.py --llama)
    sufixo = '_27b' if '--27b' in sys.argv else ''   # juiz Gemma 3 27B (preparar_juiz_kaggle.py --27b)
    if sufixo:
        KERNEL, BASE = KERNEL + '-27b', BASE.with_name(BASE.name + sufixo)
    if llama:
        KERNEL, BASE = KERNEL + '-llama', BASE.with_name(BASE.name + '_llama')
    resultados = BASE / 'resultados'
    resultados.mkdir(parents=True, exist_ok=True)
    if '--sem-download' not in sys.argv:
        subprocess.run(['kaggle', 'kernels', 'output', KERNEL, '-p', str(resultados), '-o'], check=True)
    pedidos = {json.loads(l)['pergunta_id']: json.loads(l)
               for l in (BASE / 'dataset/pedidos.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()}
    saidas = {json.loads(l)['pergunta_id']: json.loads(l)
              for l in (resultados / 'respostas.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()}
    julgamentos = []
    observabilidade = Observabilidade(BASE / 'observabilidade_importacao.jsonl')
    for jid, p in pedidos.items():
        inicio = time.monotonic()
        s = saidas.get(jid)
        registro = dict(julgamento_id=jid, grupo=p['grupo'], valido=False, erro=None)
        if p.get('erro_contexto'):
            registro['erro'] = 'context window exceeded; julgamento não executado'
        elif s is None:
            registro['erro'] = 'sem saída do kernel'
        elif s.get('pedido_sha256') != p['pedido_sha256']:
            registro['erro'] = 'hash do pedido diferente'
        else:
            try:
                registro.update(interpretar(s['resposta']), valido=True, segundos=s.get('segundos'))
            except (ValueError, TypeError) as e:
                registro['erro'] = str(e)[:200]
        observabilidade.registrar(
            'importacao_julgamento',
            status='valido' if registro['valido'] else 'invalido',
            pergunta_id=jid,
            duracao_ms=(time.monotonic() - inicio) * 1000,
            metricas={'tem_saida': s is not None},
            tipo_erro=(
                None
                if registro['valido']
                else 'context_window_exceeded'
                if p.get('erro_contexto')
                else 'validation_failed'
            ),
        )
        julgamentos.append(registro)
    with (BASE / 'julgamentos.jsonl').open('w', encoding='utf-8', newline='\n') as f:
        for j in julgamentos:
            f.write(json.dumps(j, ensure_ascii=False) + '\n')

    RELATORIOS.mkdir(parents=True, exist_ok=True)
    colunas = ['fidelidade', 'correcao', 'comportamento', 'clareza']
    tabela = pd.DataFrame([{k: j.get(k) for k in ['julgamento_id', 'grupo', 'valido', 'erro', 'veredito', 'veredito_regra', 'segundos', *colunas]}
                           | dict(afirmacoes=len(j.get('afirmacoes') or []),
                                  sem_apoio=sum(a.get('suporte') in ('sem_apoio', 'contradita') for a in j.get('afirmacoes') or []),
                                  jurisprudencia_entregue=len(j.get('jurisprudencia_pertinente') or []),
                                  jurisprudencia_pertinente=sum(bool(x.get('pertinente')) for x in j.get('jurisprudencia_pertinente') or []))
                           for j in julgamentos])
    if llama:
        tabela.to_csv(RELATORIOS / f'julgamentos{sufixo}_llama.csv', index=False, encoding='utf-8')
        print('válidos:', tabela.valido.sum(), 'de', len(tabela))
        print('modelo:', tabela.veredito.value_counts(dropna=False).to_dict(), '| regra:', tabela.veredito_regra.value_counts(dropna=False).to_dict())
        print(tabela[colunas].mean().round(2).to_dict())
        return
    humano = {}
    arquivo = glob.glob(str(ROOT / 'avaliacao/dados/legislacao/feedback_pos_teste/*/respostas_reais_e_feedback.jsonl'))[0]
    for l in Path(arquivo).read_text(encoding='utf-8').splitlines():
        if l.strip():
            r = json.loads(l)
            humano[f'calib_{r["query_id"]}'] = r['decisao_sobre_resposta_original']
    calib = tabela[tabela.grupo == 'calibracao'].assign(humano=lambda d: d.julgamento_id.map(humano))
    calib = calib.assign(concorda=calib.veredito == calib.humano, concorda_regra=calib.veredito_regra == calib.humano)
    calib.to_csv(RELATORIOS / f'calibracao{sufixo}.csv', index=False, encoding='utf-8')
    geradas = tabela[tabela.grupo == 'geracao'].copy()
    revisao = ROOT / 'dados/relatorios/integracao/geracao_v2/revisao_saida.csv'
    if revisao.exists():
        guard = pd.read_csv(revisao).set_index('pergunta_id')
        ids = geradas.julgamento_id.str.removeprefix('ger_')
        geradas['guardrail'] = ids.map(guard['aprovada']).map({True: 'aprovada', False: 'reprovada'})
        geradas['acao'] = ids.map(guard['acao'])
    geradas.to_csv(RELATORIOS / f'julgamentos{sufixo}.csv', index=False, encoding='utf-8')
    print('válidos:', tabela.valido.sum(), 'de', len(tabela))
    reprovadas = calib[calib.humano == 'reprovada']
    print('calibração (juiz × revisora): modelo', int(calib.concorda.sum()), '| regra', int(calib.concorda_regra.sum()),
          'de', len(calib), '| reprovadas pela revisora detectadas: modelo',
          int((reprovadas.veredito == 'reprovada').sum()), '| regra', int((reprovadas.veredito_regra == 'reprovada').sum()),
          'de', len(reprovadas))
    print(calib[['julgamento_id', 'humano', 'veredito', 'veredito_regra', *colunas]].to_string(index=False))
    if len(geradas):
        print('geradas — modelo:', geradas.veredito.value_counts(dropna=False).to_dict(),
              '| regra:', geradas.veredito_regra.value_counts(dropna=False).to_dict())


if __name__ == '__main__':
    main()
