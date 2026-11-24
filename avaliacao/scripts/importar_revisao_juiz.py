"""Importa a avaliação humana do rótulo cego e mede a concordância com o juiz Gemma 3 27B.

Entrada : dados/output/integracao/revisao_juiz/avaliacao_respostas_marcacoes_<revisor>.json (fora do Git: tem as observações)
          dados/relatorios/integracao/juiz/triagem_27b.csv (veredito_regra e veredito_modelo de cada resposta)
Saída   : dados/relatorios/integracao/juiz/concordancia_humano_27b.csv (só identificadores e vereditos, sem o texto das observações)

Respostas sem veredito marcado mas com observação recebem um veredito INFERIDO da observação (dicionário INFERIDO,
lido à mão); a coluna `origem` distingue 'marcado' de 'inferido_obs' e as métricas saem nos dois recortes.
Uso: python avaliacao/scripts/importar_revisao_juiz.py [arquivo.json]
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PASTA = ROOT / 'dados/output/integracao/revisao_juiz'
TRIAGEM = ROOT / 'dados/relatorios/integracao/juiz/triagem_27b.csv'
SAIDA = ROOT / 'dados/relatorios/integracao/juiz/concordancia_humano_27b.csv'

# Leitura das observações das respostas que ficaram sem veredito marcado (advogado revisor, 2026-11-22).
# O revisor reprovou até a resposta que chamou de "boa" (q_test_08), então as observações "parcial" contam como reprovação.
INFERIDO = {
    'q09_p2_FAQ26': ('reprovada', 'obs diz "Status da Geração: Reprovada"'),
    'juris_024': ('reprovada', '"insatisfatória"'),
    'juris_004': ('reprovada', '"incorreta no ponto central"'),
    'juris_013': ('reprovada', '"incorreta e potencialmente prejudicial"'),
    'juris_019': ('reprovada', '"parcialmente correta, mas com vários erros"'),
    'q09_p2_FAQ32': ('reprovada', '"parcialmente correta, com prazos desatualizados"'),
    'q09_p2_FAQ36': ('reprovada', '"incompleta para um FAQ" (leitura incerta)'),
    'q09_p2_FAQ15': ('reprovada', '"parcial", três erros na fundamentação (leitura incerta)'),
    'q_test_01': ('reprovada', '"essencial correto, conclusão contradiz" (leitura incerta)'),
    'q_dev_05': ('reprovada', '"razoável, com um erro importante" (leitura incerta)'),
}

# Tipos de falha apontados nas observações do revisor (leitura manual, uma linha por resposta, na ordem da página).
# Geração:     memoria = completa de memória / norma fora das fontes · mecanismo = distorce regra, condição ou prazo ·
#              citacao = dispositivo errado ou [Fonte N] atribuída a quem não diz aquilo · abertura = "Sim"/"Não"
#              categórico contradito depois · escopo = norma de escopo restrito aplicada a todos ou fonte certa ignorada
# Recuperação: recall = norma central não recuperada · ruido = fonte trazida por termo solto, sem relação com a pergunta
# Corpus:      precedente = a regra decisiva é súmula, OJ ou tema do TST · fronteira = pergunta de produto ou matéria
#              fora do corpus trabalhista (tributário, operacional, simulador)
TIPOS = ('memoria', 'mecanismo', 'citacao', 'abertura', 'escopo', 'recall', 'ruido', 'precedente', 'fronteira')
FAMILIA = dict(memoria='geração', mecanismo='geração', citacao='geração', abertura='geração', escopo='geração',
               recall='recuperação', ruido='recuperação', precedente='corpus', fronteira='corpus')
DIAGNOSTICO = {
    'q09_p1_JUS-019': 'mecanismo citacao ruido',
    'q09_p1_JUS-016': 'citacao escopo recall ruido',
    'q09_p2_FAQ26': 'memoria citacao ruido precedente',
    'juris_024': 'mecanismo citacao abertura recall ruido precedente',
    'q_test_08': 'mecanismo citacao',
    'juris_004': 'mecanismo citacao recall ruido precedente',
    'q09_p2_FAQ32': 'mecanismo citacao recall precedente',
    'q_test_01': 'memoria mecanismo abertura',
    'q09_p2_FAQ36': 'memoria citacao recall',
    'juris_013': 'mecanismo citacao abertura recall ruido precedente',
    'juris_019': 'mecanismo citacao abertura precedente',
    'q_dev_05': 'memoria mecanismo escopo',
    'q09_p2_FAQ15': 'mecanismo citacao recall',
    'q09_p2_FAQ08': 'memoria citacao recall ruido fronteira',
    'q09_p2_FAQ13': 'fronteira',            # observação trata de outro assunto (consulta ao DataJud)
    'q09_p2_FAQ46': 'memoria ruido fronteira',
    'q09_p2_FAQ11': 'citacao ruido fronteira',
    'q09_p2_FAQ30': 'mecanismo citacao escopo recall ruido',
    'q09_p1_JUS-007': 'memoria mecanismo escopo recall',
    'q09_p1_JUS-018': 'memoria mecanismo recall ruido',
    'q09_p2_FAQ28': 'memoria mecanismo citacao recall',
    'q09_p1_JUS-022': 'memoria citacao abertura ruido fronteira',
    'juris_017': 'memoria mecanismo citacao abertura ruido precedente',
    'q09_p1_JUS-001': 'mecanismo escopo precedente',
    'q09_p1_JUS-043': 'mecanismo citacao abertura recall ruido',
}
OBS_FORA_DO_TEMA = {'q09_p2_FAQ13'}
RESPOSTAS = ROOT / 'dados/output/kaggle/geracao/resultados/respostas.jsonl'
SEM_FONTE = ROOT / 'dados/relatorios/integracao/juiz/marcacao_fontes_geracao.csv'
DIAG = ROOT / 'dados/relatorios/integracao/juiz/diagnostico_especialista_27b.csv'


def carregar_marcacoes(arquivo):
    dados = json.loads(arquivo.read_text(encoding='utf-8'))
    linhas = {}
    for chave, valor in dados['marcacoes'].items():
        partes = chave.split('|')
        if len(partes) != 3 or partes[0] != 'cego':
            continue
        _, pid, campo = partes
        linhas.setdefault(pid, {})[campo] = valor
    # A ordem das observações no JSON é a ordem da página (P1 a P25), usada pelo revisor nos comentários.
    ordem = [k.split('|')[1] for k in dados['marcacoes'] if k.startswith('cego|') and k.endswith('|obs')]
    tabela = pd.DataFrame([{'id': pid, 'ordem': ordem.index(pid) + 1 if pid in ordem else None,
                            'veredito_marcado': c.get('veredito', ''), 'obs_caracteres': len(c.get('obs', ''))}
                           for pid, c in linhas.items()])
    return dados.get('revisor', ''), tabela


def concordancia(df, juiz):
    acerto = (df.veredito_humano == df[juiz])
    return f'{acerto.sum()}/{len(df)} ({acerto.mean():.0%})'


def main():
    arquivo = Path(sys.argv[1]) if len(sys.argv) > 1 else max(PASTA.glob('avaliacao_respostas_marcacoes_*.json'),
                                                             key=lambda p: p.stat().st_mtime)
    revisor, marc = carregar_marcacoes(arquivo)
    triagem = pd.read_csv(TRIAGEM)
    cego = triagem[triagem.no_rotulo_cego][['id', 'acao', 'veredito_regra', 'veredito_modelo', 'triagem']]
    df = cego.merge(marc, on='id', how='left')
    faltando = df[df.veredito_marcado.isna()].id.tolist()
    if faltando:
        raise SystemExit(f'respostas do rótulo cego sem nenhuma marcação no JSON: {faltando}')

    marcado = df.veredito_marcado.fillna('').ne('')
    df['origem'] = marcado.map({True: 'marcado', False: 'inferido_obs'})
    df['veredito_humano'] = df.veredito_marcado.where(marcado, df.id.map(lambda i: INFERIDO.get(i, ('', ''))[0]))
    df['motivo_inferencia'] = df.id.map(lambda i: INFERIDO.get(i, ('', ''))[1]).where(~marcado, '')
    sem = df[df.veredito_humano.eq('')].id.tolist()
    if sem:
        raise SystemExit(f'sem veredito marcado e sem leitura em INFERIDO: {sem}')
    df['revisor'] = 'advogado revisor'   # o nome fica só no JSON exportado, fora do Git

    colunas = ['ordem', 'id', 'acao', 'revisor', 'veredito_humano', 'origem', 'motivo_inferencia', 'veredito_regra',
               'veredito_modelo', 'triagem', 'obs_caracteres']
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    df = df.sort_values('ordem')
    marcado = df.origem.eq('marcado')
    df[colunas].to_csv(SAIDA, index=False, encoding='utf-8')

    # Marcação [Fonte N] nas 111 respostas da geração (contagem automática, sem o texto das respostas).
    if RESPOSTAS.exists():
        linhas = [json.loads(l) for l in RESPOSTAS.read_text(encoding='utf-8').splitlines() if l.strip()]
        marc = pd.DataFrame([{'id': r['pergunta_id'],
                              'marcacoes_fonte': len(re.findall(r'\[Fonte\s*\d+', r.get('resposta') or ''))}
                             for r in linhas])
        marc['sem_marcacao'] = marc.marcacoes_fonte.eq(0)
        marc.to_csv(SEM_FONTE, index=False, encoding='utf-8')
    marc = pd.read_csv(SEM_FONTE)

    faltam = set(df.id) - set(DIAGNOSTICO)
    if faltam:
        raise SystemExit(f'respostas sem leitura em DIAGNOSTICO: {sorted(faltam)}')
    diag = df[['ordem', 'id', 'acao', 'veredito_regra']].copy()
    for tipo in TIPOS:
        diag[tipo] = diag.id.map(lambda i: tipo in DIAGNOSTICO[i].split())
    diag['sem_marcacao_fonte'] = diag.id.map(marc.set_index('id').sem_marcacao)
    diag['obs_fora_do_tema'] = diag.id.isin(OBS_FORA_DO_TEMA)
    diag.to_csv(DIAG, index=False, encoding='utf-8')
    print('diagnóstico:', DIAG.relative_to(ROOT), '·', {t: int(diag[t].sum()) for t in TIPOS},
          '· sem [Fonte N]:', int(diag.sem_marcacao_fonte.sum()), 'de', len(diag),
          f'(geração: {int(marc.sem_marcacao.sum())} de {len(marc)})')

    print(f'revisor: {revisor} · arquivo: {arquivo.name}')
    print(f'respostas: {len(df)} · marcadas: {marcado.sum()} · inferidas da observação: {(~marcado).sum()}')
    print('humano :', df.veredito_humano.value_counts().to_dict())
    print('regra  :', df.veredito_regra.value_counts().to_dict())
    print('modelo :', df.veredito_modelo.value_counts().to_dict())
    for nome, recorte in [('só marcadas', df[marcado]), ('marcadas + inferidas', df)]:
        print(f'\nconcordância ({nome}, n={len(recorte)}):  regra {concordancia(recorte, "veredito_regra")}'
              f' · modelo {concordancia(recorte, "veredito_modelo")}')
        print(pd.crosstab(recorte.veredito_humano, recorte.veredito_regra,
                          rownames=['humano'], colnames=['regra']).to_string())
    print('\nsaída:', SAIDA.relative_to(ROOT))


if __name__ == '__main__':
    main()
