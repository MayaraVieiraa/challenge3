"""Executa e popula as células de código de notebooks em notebooks/03_integracao/."""
from pathlib import Path
from contextlib import redirect_stdout
import base64
import io
import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.figure
import matplotlib.pyplot as plt
import IPython.display


def executar(caminho):
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    path = root / caminho if not Path(caminho).is_absolute() else Path(caminho)
    nb = json.loads(path.read_text(encoding='utf-8'))
    os.chdir(path.parent)

    ns = {'__name__': '__main__'}
    count = 0
    for cell in nb['cells']:
        if cell['cell_type'] != 'code':
            continue
        count += 1
        outputs = []

        def custom_display(*values, **kwargs):
            for value in values:
                if isinstance(value, matplotlib.figure.Figure):
                    buf = io.BytesIO()
                    value.savefig(buf, format='png', dpi=110)
                    outputs.append({
                        'output_type': 'display_data',
                        'data': {'image/png': base64.b64encode(buf.getvalue()).decode(), 'text/plain': '<Figura>'},
                        'metadata': {}
                    })
                    plt.close(value)
                    continue
                data = {'text/plain': str(value)}
                if hasattr(value, '_repr_html_') and value._repr_html_():
                    data['text/html'] = value._repr_html_()
                elif type(value).__name__ == 'Markdown':
                    data['text/markdown'] = value.data
                outputs.append({'output_type': 'display_data', 'data': data, 'metadata': {}})

        def custom_show(*a, **k):
            for num in plt.get_fignums():
                buf = io.BytesIO()
                plt.figure(num).savefig(buf, format='png', dpi=110)
                outputs.append({
                    'output_type': 'display_data',
                    'data': {'image/png': base64.b64encode(buf.getvalue()).decode(), 'text/plain': '<Figura>'},
                    'metadata': {}
                })
            plt.close('all')

        IPython.display.display, plt.show = custom_display, custom_show
        ns['display'] = custom_display
        stream = io.StringIO()
        print(f'Executando: {cell.get("id") or count}', flush=True)
        with redirect_stdout(stream):
            exec(compile(''.join(cell['source']), cell.get('id') or f'celula_{count}', 'exec'), ns)
        custom_show()
        if stream.getvalue():
            outputs.insert(0, {'output_type': 'stream', 'name': 'stdout', 'text': stream.getvalue()})
        cell.update(execution_count=count, outputs=outputs)

    path.write_text(json.dumps(nb, indent=2, ensure_ascii=False), encoding='utf-8')
    print('Notebook executado e salvo com sucesso:', path)


if __name__ == '__main__':
    alvo = sys.argv[1] if len(sys.argv) > 1 else 'notebooks/03_integracao/03_geracao.ipynb'
    executar(alvo)
