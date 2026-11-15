# Rebuilding the complete version 1.4.0 reports

These reports extend the complete English and Chinese W5 documents in `../w5/`. The original five research chapters, figures, tables, native equations, references and contribution declaration are retained. Only the cover revision and note are updated; Appendix D adds the version-bound engineering evidence. Earlier report files are not overwritten.

1. Install `python-docx` in a document environment and run `python reports/v1.4.0/build_reports.py`. It requires the checked `validation-summary.json`, resolves both appendix templates, writes the full DOCX reports, and verifies the original table contents and embedded figure bytes.
2. On Windows with Word installed, run `export_reports.ps1` explicitly with PowerShell 7. It creates a private hidden Word instance, updates the existing contents field and page numbers, and exports the two complete PDFs. It closes only that private instance.
3. Render every PDF page with Poppler and inspect the cover, contents, research pages and Appendix D at a readable scale. Verify the original numerical tables and native equations against the retained baseline. Check headings, clipping, page breaks and links.

The validation summary binds actual source, wheel, native-flow and packaging results. Updating text is not a substitute for those checks. Fixed-input timing belongs to the preflight source identity; final native acceptance and clock-boundary repairs are identified separately. No build step publishes the reports or signs the owner's E12 acceptance.

中文：两份完整报告沿用 W5 的全部研究正文，定向更新封面并增补附录 D。构建器核对原表格和图片，Word 导出更新目录与分页，最终需实际渲染并检查全部页面。性能对照与最终原生验收分别绑定版本，未代签负责人操作，也未发布。

Run `python reports/v1.4.0/check_reports.py` with `python-docx`, `lxml` and `pypdf` to check exact original body paragraphs, tables, figure bytes and equation structure, plus the resolved appendix text in the final PDF. `report-validation.json` and `visual-qa.json` record the delivered documents. PDF extraction excludes the page-number footer before comparing paragraphs that span pages.

The visual/data revision adds D.6, one unaltered final-display screenshot and one English five-pair timing figure shared by both report languages. Figure 4-1 and the original research figures retain their historical evidence. Rebuild the new plot through `../../figures/v140/build_figure.py` using its checked CSV. Contents text uses 10.5 pt so the additional entry fits without an empty overflow page.

The timing figure inherits the original P07 research style directly from `analysis/p07/presentation_figures.py`. All labels inside that figure are English. The previous bilingual, monochrome candidate is retained only in the earlier local review packet.
