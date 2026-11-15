"""Verify full-document fidelity and final PDF structure, separate from visual QA."""
import hashlib,json,re,difflib
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E
from docx import Document
from pypdf import PdfReader
root=Path(__file__).resolve().parents[2];out={};ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
normalize=lambda s:''.join(s.split()).replace('\u00ad','')
for lang,expected in [('en',33),('zh',29)]:
 old=root/f'reports/w5/report-mic-{lang}_w5-candidate-r2.docx';new=root/f'reports/v1.4.0/report-mic-{lang}_v1.4.0.docx';pdf=new.with_suffix('.pdf')
 before=Document(old);after=Document(new)
 assert [[c.text for r in t.rows for c in r.cells] for t in before.tables]==[[c.text for r in t.rows for c in r.cells] for t in after.tables]
 a=[p.text for p in before.paragraphs];b=[p.text for p in after.paragraphs]
 changes=[op for op in difflib.SequenceMatcher(None,a,b,autojunk=False).get_opcodes() if op[0]!='equal']
 assert len(changes)==4 and changes[:3]==[('replace',3,4,3,4),('replace',5,6,5,6),('insert',49,49,49,56)] and changes[3][:5]==('insert',261,261,268,len(b)),changes
 changed=[(i,a[i],b[k]) for tag,i,j,k,l in changes if tag=='replace']
 assert all('\t' in p for p in b[49:56])
 assert b[269].startswith(('Appendix D','附录 D'))
 with ZipFile(old) as a,ZipFile(new) as b:
  media=[n for n in a.namelist() if n.startswith('word/media/')]
  assert all(a.read(n)==b.read(n) for n in media)
  old_xml=E.fromstring(a.read('word/document.xml'));new_xml=E.fromstring(b.read('word/document.xml'))
  math=lambda x:[E.tostring(n,method='c14n') for n in x.findall('.//m:oMath',ns)]
  # Word may rewrite namespace declarations, so compare complete math text and structural tags.
  shape=lambda x:[[(n.tag,n.text) for n in m.iter()] for m in x.findall('.//m:oMath',ns)]
  assert shape(old_xml)==shape(new_xml)
 reader=PdfReader(pdf);assert len(reader.pages)==expected
 pages=[]
 for p in reader.pages:
  body=[]
  p.extract_text(visitor_text=lambda text,cm,tm,font,size: body.append(text) if tm[5]>45 else None)
  pages.append(''.join(body))
 text='\n'.join(pages)
 assert all(len(p.strip())>30 for p in pages)
 assert '1.4.0' in text and '1,343' in text and '391.935' in text
 assert '{{' not in text
 appendix=(root/f'reports/v1.4.0/engineering-update-{lang}-final.md').read_text('utf-8')
 for block in appendix.split('\n\n'):
  if block.strip()=='[PAGEBREAK]' or block.startswith('!['):continue
  block=re.sub('^#+ ','',block)
  assert normalize(block) in normalize(text),block[:100]
 out[lang]=dict(pages=len(pages),original_paragraphs=len(before.paragraphs),changed_original_paragraphs=changed,original_tables=len(before.tables),equations=len(shape(old_xml)),original_figures=len(media),new_figures=2,figures_byte_identical=True,math_unchanged=True,appendix_text_present=True,docx_sha256=sha(new),pdf_sha256=sha(pdf),pdf_links=sum(len(p.get('/Annots',[])) for p in reader.pages))
(root/'reports/v1.4.0/report-validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps(out,ensure_ascii=False))


