"""Extend the complete reviewed reports using verified local engineering facts."""
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches, Pt


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(here):
    facts = json.loads((here / 'validation-summary.json').read_bytes())
    if not facts['full_checks_passed'] or not facts['native_required_flows_passed']:
        raise ValueError('Complete functional validation is required before report export')
    records = {}
    for language in ('en', 'zh'):
        baseline = here.parent / 'w5' / f'report-mic-{language}_w5-candidate-r2.docx'
        original = Document(baseline)
        doc = Document(baseline)
        revision = next(p for p in doc.paragraphs if 'P08 W5 |' in p.text)
        revision.text = '\n'.join(revision.text.split('\n')[:-1] + [
            'Application v1.4.0 | Local validation edition' if language == 'en'
            else '应用 v1.4.0 | 本地验证版'])
        prefix = 'The report documents' if language == 'en' else '本报告记录已实现'
        note = next(p for p in doc.paragraphs if p.text.startswith(prefix))
        note.add_run(' Appendix D records version 1.4.0 native acceptance and release preparation; publication remains pending.'
                     if language == 'en' else '附录 D 增补 1.4.0 版原生验收与发布准备，尚未发布。')
        source = here / f'engineering-update-{language}.md'
        body = source.read_text('utf-8')
        for field, value in facts['text'][language].items():
            body = body.replace('{{' + field + '}}', value)
        if '{{' in body:
            raise ValueError('Unresolved evidence field')
        (here / f'engineering-update-{language}-final.md').write_text(body, 'utf-8')
        doc.add_page_break()
        for block in body.strip().split('\n\n'):
            if block == '[PAGEBREAK]':
                doc.add_page_break()
                continue
            if block.startswith('!['):
                match = re.fullmatch(r'!\[([^\]]+)\]\(([^)]+)\)', block)
                if not match:
                    raise ValueError('Invalid figure reference')
                picture = (here / match.group(2)).resolve()
                if not picture.is_file():
                    raise ValueError(f'Missing figure: {picture}')
                doc.add_picture(str(picture), width=Inches(6.4))
                continue
            if block.startswith('# '):
                p = doc.add_paragraph(block[2:], style='Heading 1')
            elif block.startswith('## '):
                p = doc.add_paragraph(block[3:], style='Heading 2')
            else:
                p = doc.add_paragraph(block, style='Normal')
                p.paragraph_format.space_after = Pt(6 if language == 'en' else 3)
                p.paragraph_format.widow_control = True
                if re.match(r'^(Figure D-|图 D-)\d+\. ', block):
                    for run in p.runs:
                        run.bold = True
            for run in p.runs:
                if language == 'zh':
                    run.font.name = 'Times New Roman'
                    run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), '宋体')
        # Tables, equations and existing figures are retained, without redrawing.
        assert [[c.text for r in t.rows for c in r.cells] for t in original.tables] == [
            [c.text for r in t.rows for c in r.cells] for t in doc.tables]
        doc.core_properties.author = 'Project author'
        doc.core_properties.last_modified_by = 'Project author with AI assistance'
        target = here / f'report-mic-{language}_v1.4.0.docx'
        doc.save(target)
        with ZipFile(baseline) as old, ZipFile(target) as new:
            for name in old.namelist():
                if name.startswith('word/media/'):
                    assert old.read(name) == new.read(name), name
        records[language] = dict(baseline=baseline.name, baseline_sha256=sha(baseline),
                                original_paragraphs=len(original.paragraphs),
                                original_tables=len(original.tables),
                                figures_preserved=True, appendix_sha256=sha(source),
                                docx_before_word_fields_sha256=sha(target))
    (here / 'report-build.json').write_text(json.dumps(records, indent=2), 'utf-8')


if __name__ == '__main__':
    build(Path(__file__).resolve().parent)
