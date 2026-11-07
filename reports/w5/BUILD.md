# Rebuilding the complete W5 candidate reports

The English and Chinese reports retain the reviewed five-chapter documents supplied in `baseline/`, including their figures, eight tables, native equations, references and contribution declaration. The public baseline copies change only private Word account metadata to the role Project author; `baseline/provenance.json` binds the original and sanitized hashes. The original body and media bytes are unchanged. New engineering evidence is in Appendix C. The cover revision and the short cover note identify this candidate. Original reviewed DOCX/PDF files are not overwritten.

Inputs in this directory are `engineering-addendum-en.md`, `engineering-addendum-zh.md` and `validation-summary.json`. The Markdown files are templates; the builder inserts the actual complete checks and Kit outcome from the validation summary. It also writes final resolved Markdown copies. Both complete DOCX files remain editable in Word.

1. Use Python with `python-docx` and run `python reports/w5/build_w5_reports.py` from the repository root. This generates both complete Word documents and `report-build.json`, and verifies that original figure bytes remain intact. The builder refuses a validation summary without complete source and isolated-wheel success.
2. On Windows with Microsoft Word installed, invoke PowerShell 7 explicitly and run `reports/w5/export_w5_reports.ps1`. Word updates the table of contents and pagination and exports both complete PDFs. The script records page, table and native equation counts in `word-export.json`. It uses a private Word application instance and closes it normally.
3. Render both PDFs using Poppler `pdftoppm` and inspect the cover, contents, all research pages and Appendix C at a readable scale. Check for clipping, overlap, missing glyphs, page-number errors and broken links. Compare the original table contents, math text and embedded image hashes with the reviewed documents. The candidate QA record describes the actual render/export route.

The build does not run the simulator, invent an owner acceptance record or publish files. Engineering measurements retain their original version identities. Changing the evidence summary requires new validation and review; the build script is not a substitute for those checks.

中文：两份完整报告从原审定 Word 定向增补附录 C，原研究图表、公式、引用与贡献声明保持。先运行 Python 构建器，再使用 PowerShell 7 调用 Word 导出脚本，最后实际渲染并检查 PDF。原审定版本不覆盖。构建不会运行仿真、代签 E12 或发布文件。

Revision r2 adds Section C.6 about public/private delivery boundaries, exact public checksums and fail-closed publication. The original five research figures and measurements remain unchanged.

Current r2 outputs use the suffix _w5-candidate-r2.docx and .pdf. Inputs use engineering-addendum-en-r2.md and engineering-addendum-zh-r2.md; build/export records use -r2.json. Earlier un-suffixed r1 deliverables, templates and records remain intact. The current builder/exporter regenerates r2 only.
