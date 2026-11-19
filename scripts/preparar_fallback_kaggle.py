"""Prepara a segunda passada da geração: a LLM B (Llama 3.1 8B) nos pedidos em que a LLM A falhou.

A decisão é a mesma do fluxo em tempo real (`geracao.motivo_fallback`): falha técnica ou guardrail bloqueante.
Com --todas, a B gera para todos os pedidos com LLM, para comparar os dois modelos (a resposta final continua
sendo a da A quando ela serve).

Saídas (fora do Git):
  output/kaggle/fallback_v2/dataset/pedidos.jsonl + dataset-metadata.json
  output/kaggle/fallback_v2/kernel/gerar_respostas.py + kernel-metadata.json
Depois: kaggle datasets create/version, kaggle kernels push e
        python scripts/importar_geracao_kaggle.py --sem-download --fallback
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.integracao.geracao import motivo_fallback, pedido_fallback

USUARIO_KAGGLE = 'laisapaiva93'
DATASET = 'lexia-fallback-pedidos-v2'
KERNEL = 'lexia-fallback-llama31-v2'
GERACAO = ROOT / 'output/kaggle/geracao_v2'
DESTINO = ROOT / 'output/kaggle/fallback_v2'


def main():
    todas = '--todas' in sys.argv
    pedidos = [json.loads(l) for l in (GERACAO / 'dataset/pedidos.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    respostas = {}
    for l in (GERACAO / 'resultados/respostas.jsonl').read_text(encoding='utf-8').splitlines():
        if l.strip():
            r = json.loads(l)
            respostas[r['pergunta_id']] = r
    selecionados, motivos = [], {}
    for p in pedidos:
        if not p['precisa_llm']:
            continue
        motivo = motivo_fallback(p, respostas.get(p['pergunta_id']))
        if motivo:
            motivos[p['pergunta_id']] = motivo
        if motivo or todas:
            selecionados.append(dict(pedido_fallback(p), motivo_fallback=motivo))
    print(f'{len(motivos)} pedidos com falha da LLM A', motivos if motivos else '')
    if not selecionados:
        print('Nenhum pedido precisa da LLM B. Use --todas para gerar com a B mesmo assim (comparação).')
        return
    (DESTINO / 'dataset').mkdir(parents=True, exist_ok=True)
    with (DESTINO / 'dataset/pedidos.jsonl').open('w', encoding='utf-8', newline='\n') as f:
        for p in selecionados:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    (DESTINO / 'dataset/dataset-metadata.json').write_text(json.dumps(dict(
        title=DATASET, id=f'{USUARIO_KAGGLE}/{DATASET}', licenses=[dict(name='unknown')],
        description='Pedidos privados da LLM B (fallback) do LexIA. Não redistribuir.'), indent=2), encoding='utf-8')
    (DESTINO / 'kernel').mkdir(parents=True, exist_ok=True)
    (DESTINO / 'kernel/kernel-metadata.json').write_text(json.dumps(dict(
        id=f'{USUARIO_KAGGLE}/{KERNEL}', title=KERNEL, code_file='gerar_respostas.py', language='python',
        kernel_type='script', is_private=True, enable_gpu=True, enable_tpu=False, enable_internet=True,
        machine_shape='NvidiaTeslaT4', dataset_sources=[f'{USUARIO_KAGGLE}/{DATASET}'], competition_sources=[],
        kernel_sources=[], model_sources=[]), indent=2), encoding='utf-8')
    (DESTINO / 'kernel/gerar_respostas.py').write_text((ROOT / 'scripts/kaggle_gerar_respostas.py').read_text(encoding='utf-8'),
                                                       encoding='utf-8')
    print(f'{len(selecionados)} pedidos para a LLM B ({"todos, para comparação" if todas else "só as falhas"})')


if __name__ == '__main__':
    main()
