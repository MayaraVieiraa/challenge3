"""Kernel do Kaggle (GPU T4): geração em duas etapas do LexIA (v3.4) com Qwen3 8B no Ollama.

Para cada pedido que precisa de LLM:
  1. escolha: chamada com saída estruturada (esquema JSON do pedido): até 2 números de fonte e o que falta;
  2. redação: chamada em texto livre só com as fontes escolhidas (src/integracao/duas_etapas.py).
A lógica das etapas vem de duas_etapas.py e prompt_juridico.py, que vão no dataset junto com pedidos.jsonl.
Cada resposta é validada como no kernel de uma etapa (não vazia, não cortada, sem raciocínio interno); uma resposta
cortada é refeita com limite maior de tokens. Grava respostas.jsonl de forma incremental em /kaggle/working.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA_VERSAO = '0.40.16'
LIMITE_SEGUNDOS = 11 * 3600
SAIDA = Path('/kaggle/working/respostas.jsonl')
URL = 'http://127.0.0.1:11434'

sys.path.insert(0, str(Path(glob.glob('/kaggle/input/**/duas_etapas.py', recursive=True)[0]).parent))
import duas_etapas  # noqa: E402


def sh(comando):
    print('$', comando, flush=True)
    subprocess.run(comando, shell=True, check=True)


def chamar(caminho, corpo=None, timeout=1800):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(URL + caminho, dados, {'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def fabricar_chat(modelo):
    def chat(mensagens, opcoes, formato):
        opcoes = dict(opcoes)
        tentativas, r, texto = [], {}, None
        for _ in range(3):
            t = time.monotonic()
            corpo = dict(model=modelo, messages=mensagens, stream=False, think=False, options=opcoes)
            if formato is not None:
                corpo['format'] = formato
            try:
                r = chamar('/api/chat', corpo)
            except Exception as erro:
                tentativas.append(dict(erro=str(erro)[:300]))
                time.sleep(10)
                continue
            texto = r['message']['content']
            minimo = 2 if formato is not None else 80
            problema = ('cortada' if r.get('done_reason') == 'length' else
                        'vazia' if len(texto.strip()) < minimo else
                        'raciocinio' if re.search(r'</?think>', texto) else None)
            tentativas.append(dict(segundos=round(time.monotonic() - t, 1), done_reason=r.get('done_reason'), problema=problema))
            if problema is None:
                break
            if problema == 'cortada':
                opcoes['num_predict'] = int(opcoes.get('num_predict', 1200)) * 2
        ok = bool(tentativas) and 'erro' not in tentativas[-1]
        return (texto if ok else None), dict(done_reason=r.get('done_reason') if ok else None,
                                             prompt_tokens=r.get('prompt_eval_count'), tokens_saida=r.get('eval_count'),
                                             segundos=sum(x.get('segundos', 0) for x in tentativas), tentativas=tentativas,
                                             opcoes=opcoes)
    return chat


inicio = time.monotonic()
sh('apt-get install -y -q zstd > /dev/null 2>&1 || true')
sh(f'curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION={OLLAMA_VERSAO} sh')
log = open('/kaggle/working/ollama.log', 'w')
subprocess.Popen(['ollama', 'serve'], env={**os.environ, 'OLLAMA_KEEP_ALIVE': '-1'}, stdout=log, stderr=log)
for _ in range(60):
    try:
        chamar('/api/tags', timeout=5)
        break
    except Exception:
        time.sleep(2)

arquivo = glob.glob('/kaggle/input/**/pedidos.jsonl', recursive=True)[0]
pedidos = [json.loads(l) for l in open(arquivo, encoding='utf-8') if l.strip()]
for m in sorted({p['modelo'] for p in pedidos if p.get('precisa_llm')}):
    sh(f'ollama pull {m}')
print(chamar('/api/version'), flush=True)

feitos = set()
if SAIDA.exists():
    feitos = {json.loads(l)['pergunta_id'] for l in SAIDA.read_text(encoding='utf-8').splitlines() if l.strip()}
pendentes = [p for p in pedidos if p.get('precisa_llm') and p['pergunta_id'] not in feitos]
print(f'{len(pedidos)} pedidos, {len(pendentes)} para gerar', flush=True)

with SAIDA.open('a', encoding='utf-8') as saida:
    for i, p in enumerate(pendentes, 1):
        if time.monotonic() - inicio > LIMITE_SEGUNDOS:
            print('limite de tempo atingido; respostas parciais salvas', flush=True)
            break
        registro = duas_etapas.gerar(p, fabricar_chat(p['modelo']))
        info = registro['info_redacao']
        registro.update(modelo=p['modelo'], done_reason=info['done_reason'], prompt_tokens=info['prompt_tokens'],
                        tokens_saida=info['tokens_saida'],
                        segundos=round(registro['info_escolha']['segundos'] + info['segundos'], 1))
        saida.write(json.dumps(registro, ensure_ascii=False) + '\n')
        saida.flush()
        print(f"{i}/{len(pendentes)} {p['pergunta_id']} fontes {registro['escolhidas']} "
              f"{registro['info_escolha']['segundos']:.1f}s + {info['segundos']:.1f}s {info['tentativas'][-1] if info['tentativas'] else ''}",
              flush=True)

linhas = [json.loads(l) for l in SAIDA.read_text(encoding='utf-8').splitlines() if l.strip()]
validas = [l for l in linhas if l['resposta'] and l['info_redacao']['tentativas']
           and l['info_redacao']['tentativas'][-1].get('problema') is None]
resumo = dict(pedidos_llm=sum(1 for p in pedidos if p.get('precisa_llm')), respostas=len(linhas), validas=len(validas),
              segundos_medios=round(sum(l['segundos'] for l in linhas) / max(len(linhas), 1), 1),
              segundos_medios_escolha=round(sum(l['info_escolha']['segundos'] for l in linhas) / max(len(linhas), 1), 1),
              fontes_escolhidas={str(k): sum(1 for l in linhas if len(l['escolhidas']) == k) for k in range(3)},
              ollama=chamar('/api/version'), gpu=subprocess.run('nvidia-smi --query-gpu=name,memory.total --format=csv,noheader',
                                                                 shell=True, capture_output=True, text=True).stdout.strip())
Path('/kaggle/working/resumo.json').write_text(json.dumps(resumo, indent=2), encoding='utf-8')
print(resumo, flush=True)
