"""Extend both reviewed reports with the version-bound engineering evidence.

Run with python-docx. Export the resulting documents with export_w5_reports.ps1.
"""

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(here):
    facts = json.loads((here / 'validation-summary.json').read_text('utf8'))
    if not facts['full_checks']['passed']:
        raise ValueError('Final full source and isolated-wheel validation is required')
    changes = {}
    for language in ('en', 'zh'):
        baseline = here / f'baseline/report-mic-{language}_reviewed.docx'
        doc = Document(baseline)
        source = here / f'engineering-addendum-{language}-r2.md'
        text = source.read_text('utf8')
        if language == 'en':
            checks = facts['full_checks']['rounds']
            validation = (
                f'The exact candidate passed the unchanged scripts/check.py entry point: '
                f'{checks[0]["tests"]} tests in the source round and {checks[1]["tests"]} tests '
                f'in the isolated-wheel round. Ruff, locked dependencies, wheel/sdist building '
                f'and dependency checks also passed. Eleven new ownership and fallback tests '
                f'cover both concurrent exit orders, single/both exceptions, nesting, immutable '
                f'record sharing, private mutable containers, the original full Python path '
                f'and geometry-cache separation. Twelve evidence tests and two publication '
                f'guards reject altered plans, proofs, STOP receipts, process identities, '
                f'final saved state and invalid timing intervals, including under Python -O. '
                f'The original independent verifier retained the same four negative-case reasons. '
                f'The portable CPU/Qt chain displayed v1, retained v1 during a change, independently '
                f'verified v2 and saved STOPPED/COMPLETE with worker exit 0. Its STOP was accepted '
                f'once. Bilingual STOP recovery and read-only/fallback archive views also passed. '
                f'Three sets of 40 candidate Qt fixture samples had p95 input, bridge and stage '
                f'presentation delays of {facts["qt_p95_ms"][0]:.1f} ms, '
                f'{facts["qt_p95_ms"][1]:.1f} ms and {facts["qt_p95_ms"][2]:.1f} ms. '
                f'The recorded sandbox renderer failures were retained; the functioning Qt and '
                f'EXE checks used the normal local process environment.'
            )
            kit = facts['report_kit_en']
            revision = 'P08 W5 | Local integration candidate v1.1.0 r2'
            addition = ' Appendix C records the subsequent W1 to W5 engineering candidate.'
        else:
            checks = facts['full_checks']['rounds']
            validation = (
                f'确切候选通过原 scripts/check.py 完整入口：源码轮 {checks[0]["tests"]} 项、'
                f'隔离 wheel 轮 {checks[1]["tests"]} 项测试通过，Ruff、锁定依赖、wheel/sdist 构建'
                f'和依赖检查也通过。11 项新增所有权与回退测试覆盖两种并发退出顺序、单方及双方异常、'
                f'嵌套调用、不可变记录共享、可变容器隔离、原完整 Python 路径和几何缓存隔离。'
                f'12 项证据测试与两项发布保护拒绝计划、证明、STOP 回执、进程身份、最终保存状态及'
                f'非法计时区间的篡改，包含 Python -O 下的拒绝。原独立核验器保持四类坏件的拒绝原因。'
                f'便携 CPU/Qt 链显示 v1、改单时保留 v1、独立核验 v2，并保存 STOPPED/COMPLETE，'
                f'工作进程退出 0，STOP 只受理一次。双语 STOP 恢复及只读/回退存档显示也通过。'
                f'候选 Qt 夹具三组各 40 个样本，输入、桥接及阶段呈现延迟 p95 分别为 '
                f'{facts["qt_p95_ms"][0]:.1f} ms、{facts["qt_p95_ms"][1]:.1f} ms、'
                f'{facts["qt_p95_ms"][2]:.1f} ms。受限环境中的渲染失败保留，功能通过的 Qt 和 '
                f'EXE 检查使用正常本机进程环境。'
            )
            kit = facts['report_kit_zh']
            revision = 'P08 W5 | 本地集成候选 v1.1.0 r2'
            addition = '附录 C 记录此后的 W1 至 W5 工程候选。'
        text = text.replace('{{VALIDATION}}', validation).replace('{{KIT}}', kit)
        if '{{' in text:
            raise ValueError('Unresolved report field')
        source.with_name(f'engineering-addendum-{language}-r2-final.md').write_text(text,'utf8')
        revision_paragraph = next(p for p in doc.paragraphs if 'P08-r2 |' in p.text)
        first_lines = revision_paragraph.text.split('\n')[:-1]
        revision_paragraph.text = '\n'.join((*first_lines, revision))
        cover_prefix = 'The report documents' if language == 'en' else '本报告记录已实现'
        cover_note = next(p for p in doc.paragraphs if p.text.startswith(cover_prefix))
        cover_note.add_run(addition)
        doc.add_page_break()
        for block in text.strip().split('\n\n'):
            block = block.strip()
            if block.startswith('# '):
                paragraph = doc.add_paragraph(block[2:], style='Heading 1')
            elif block.startswith('## '):
                paragraph = doc.add_paragraph(block[3:], style='Heading 2')
                if block.startswith('## C.6 '):
                    paragraph.paragraph_format.page_break_before = True
            else:
                paragraph = doc.add_paragraph(block, style='Normal')
                paragraph.paragraph_format.space_after = Pt(6 if language == 'en' else 1)
                paragraph.paragraph_format.widow_control = True
            for run in paragraph.runs:
                if language == 'zh':
                    run.font.name = 'Times New Roman'
                    run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), '宋体')
        doc.core_properties.author = 'Project author'
        doc.core_properties.last_modified_by = 'Project author with AI assistance'
        target = here / f'report-mic-{language}_w5-candidate-r2.docx'
        doc.save(target)
        with ZipFile(baseline) as old, ZipFile(target) as new:
            media = lambda z: sorted(digest_bytes(z.read(n)) for n in z.namelist()
                                     if n.startswith('word/media/'))
            if media(old) != media(new):
                raise ValueError('Original figure bytes changed')
        changes[language] = dict(source_sha256=digest(baseline),docx_sha256_before_word_fields=digest(target),
                                 original_paragraphs=len(Document(baseline).paragraphs),
                                 original_tables=len(doc.tables), figures_preserved=True,
                                 appendix_source_sha256=digest(source))
    (here/'report-build-r2.json').write_text(json.dumps(changes,indent=2),'utf8')


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


if __name__ == '__main__':
    build(Path(__file__).resolve().parent)
