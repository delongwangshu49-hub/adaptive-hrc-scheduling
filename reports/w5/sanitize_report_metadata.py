"""Replace Word account metadata with role names without changing document content."""

from pathlib import Path
from xml.etree import ElementTree as E
from zipfile import ZipFile

for prefix, uri in (
    ('cp', 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties'),
    ('dc', 'http://purl.org/dc/elements/1.1/'),
    ('dcterms', 'http://purl.org/dc/terms/'),
    ('xsi', 'http://www.w3.org/2001/XMLSchema-instance'),
):
    E.register_namespace(prefix, uri)


def sanitize(path):
    temporary = path.with_name(path.name + '.metadata-tmp')
    with ZipFile(path) as old, ZipFile(temporary, 'w') as new:
        for item in old.infolist():
            data = old.read(item.filename)
            if item.filename == 'docProps/core.xml':
                xml = E.fromstring(data)
                for element in xml:
                    if element.tag.rsplit('}', 1)[-1] in ('creator', 'lastModifiedBy'):
                        element.text = 'Project author'
                data = E.tostring(xml, encoding='utf-8', xml_declaration=True)
            new.writestr(item, data)
    temporary.replace(path)


if __name__ == '__main__':
    for document in Path(__file__).resolve().parent.glob('report-mic-*_w5-candidate-r2.docx'):
        sanitize(document)
