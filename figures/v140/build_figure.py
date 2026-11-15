"""Rebuild the English replay figure using the existing P07 figure style."""
import ast
import csv
import hashlib
import json
import os
from pathlib import Path

here = Path(__file__).resolve().parent
root = here.parents[1]
os.environ.setdefault('MPLCONFIGDIR', str(root / '.local/v140-figure-cache'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


def original_style():
    """Read the existing literal style without modifying or running its analysis."""
    path = root / 'analysis/p07/presentation_figures.py'
    tree = ast.parse(path.read_text('utf-8'))
    colors = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ('HUMAN', 'COLLAB', 'INK'):
                colors[node.targets[0].id] = ast.literal_eval(node.value)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_figures')
    assignment = next(n for n in function.body if isinstance(n, ast.Assign)
                      and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'style')
    return ast.literal_eval(assignment.value), colors, path


def main():
    rows = list(csv.DictReader((here / 'paired-replay.csv').open(encoding='utf-8')))
    facts = json.loads((here / 'paired-replay-data.json').read_bytes())
    assert len(rows) == facts['measured_pairs'] == 5
    style, colors, reference = original_style()
    gray, blue, ink = (colors[n] for n in ('HUMAN', 'COLLAB', 'INK'))
    outputs = {}
    with plt.rc_context(style):
        fig, ax = plt.subplots(figsize=(8.2, 6.0))
        fig.subplots_adjust(left=.14, right=.84, top=.78, bottom=.23)
        for i, row in enumerate(rows):
            disabled, restored, y = float(row['disabled_s']), float(row['restored_s']), 5-i
            ax.plot([disabled, restored], [y, y], color='#aab2bd', lw=2, zorder=1)
            ax.scatter([disabled], [y], marker='o', s=70, facecolors='white',
                       edgecolors=gray, lw=1.8, zorder=3)
            ax.scatter([restored], [y], marker='s', s=65, color=blue, zorder=3)
            ax.annotate(f'{disabled:.1f}', (disabled, y), xytext=(0, 13),
                        textcoords='offset points', ha='center', fontsize=11, color=gray)
            ax.annotate(f'{restored:.1f}', (restored, y), xytext=(0, -21),
                        textcoords='offset points', ha='center', fontsize=11, color=blue)
            ax.text(333, y, f"{float(row['change_percent']):+.1f}%", va='center',
                    ha='left', fontsize=12, weight='bold', color=ink)
        ax.set(xlim=(0, 320), ylim=(.35, 5.65), yticks=[1, 2, 3, 4, 5],
               yticklabels=['5', '4', '3', '2', '1'], xticks=[0, 60, 120, 180, 240, 300],
               xlabel='Total CPU replay wall time (s); lower is faster', ylabel='Pair')
        ax.grid(axis='x', alpha=.18)
        ax.axvline(60, color=gray, lw=1, ls='--')
        ax.text(60, .03, '60 s target', transform=ax.get_xaxis_transform(),
                ha='center', va='bottom', fontsize=10, color=gray)
        ax.text(333, 5.7, 'Change', fontsize=11, ha='left', va='bottom')
        fig.suptitle('Four of five fixed-input pairs became faster', fontsize=16, y=.975)
        fig.legend(handles=[
            Line2D([], [], color=gray, marker='o', markerfacecolor='white', ls='',
                   label='Reuse recognition disabled'),
            Line2D([], [], color=blue, marker='s', ls='', label='Reuse restored'),
        ], loc='upper center', bbox_to_anchor=(.5, .91), ncol=1, frameon=False, fontsize=11)
        fig.text(.08, .035,
                 'Five same-machine pairs; two warm-ups excluded. Preflight CPU replay,\n'
                 'not final native end-to-end timing. Variant medians: 273.498 to 230.917 s\n'
                 '(15.57% lower); median within-pair reduction: 12.25%.',
                 fontsize=10, color=gray)
        for ext in ('png', 'svg', 'pdf'):
            path = here / f'V140-paired-replay-en.{ext}'
            metadata = {'Date': None} if ext == 'svg' else (
                {'CreationDate': None, 'ModDate': None} if ext == 'pdf' else {})
            fig.savefig(path, dpi=300, bbox_inches=None, metadata=metadata)
            outputs[path.name] = dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        plt.close(fig)
    manifest = dict(scope=facts['scope'], language='English',
                    style_reference=reference.relative_to(root).as_posix(),
                    style_reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                    inherited_rcparams=style, inherited_palette=colors,
                    data_sha256=hashlib.sha256((here/'paired-replay.csv').read_bytes()).hexdigest(),
                    facts_sha256=hashlib.sha256((here/'paired-replay-data.json').read_bytes()).hexdigest(),
                    transformations='Original five matched observations; declared warm-ups excluded; linear axis; no CI, smoothing or omitted slow pair.',
                    outputs=outputs)
    (here/'figure-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', 'utf-8')
    print(json.dumps(dict(figures=1, language='English', files=3, observations=10)))


if __name__ == '__main__':
    main()
