import json
import os
import re
import zipfile
from datetime import datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt


def _safe_filename(name):
    return re.sub(r'[\\/*?:"<>|]+', "_", name).strip()


def _make_para_rtl(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    bidi.set(qn("w:val"), "1")
    pPr.append(bidi)


def _add_rtl_run(paragraph, text, bold=False):
    run = paragraph.add_run(str(text or ""))
    run.bold = bold
    rPr = run._r.get_or_add_rPr()
    rtl = OxmlElement("w:rtl")
    rtl.set(qn("w:val"), "1")
    rPr.append(rtl)
    return run


def _add_rtl_heading(doc, text, level=1):
    h = doc.add_heading("", level=level)
    _make_para_rtl(h)
    _add_rtl_run(h, text, bold=True)
    return h


def _add_rtl_paragraph(doc, label="", value="", bullet=False):
    p = doc.add_paragraph(style="List Bullet" if bullet else None)
    _make_para_rtl(p)
    if label:
        _add_rtl_run(p, f"{label}: ", bold=True)
    if value:
        _add_rtl_run(p, value, bold=False)
    return p


def _make_table_rtl(table):
    tblPr = table._tbl.tblPr
    bidiVisual = OxmlElement("w:bidiVisual")
    tblPr.append(bidiVisual)


def _fill_rtl_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    _make_table_rtl(table)

    hdr_cells = table.rows[0].cells
    for i, htext in enumerate(headers):
        hdr_cells[i].text = ""
        p = hdr_cells[i].paragraphs[0]
        _make_para_rtl(p)
        _add_rtl_run(p, htext, bold=True)

    for r_idx, row_vals in enumerate(rows, 1):
        cells = table.rows[r_idx].cells
        for c_idx, val in enumerate(row_vals):
            cells[c_idx].text = ""
            p = cells[c_idx].paragraphs[0]
            _make_para_rtl(p)
            _add_rtl_run(p, str(val), bold=False)
    return table


def _configure_arabic_docx():
    doc = Document()
    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Arial"
    normal_style.font.size = Pt(11.5)
    for sec in doc.sections:
        sec.top_margin = Inches(0.8)
        sec.bottom_margin = Inches(0.8)
        sec.left_margin = Inches(0.8)
        sec.right_margin = Inches(0.8)
    return doc


def _count_novel_sections_words(novel):
    # تقدير دقيق لعدد كلمات التحليل المُصدّر لهذه الرواية
    raw = json.dumps(novel.get("sections", {}), ensure_ascii=False)
    # نحسب الكلمات العربية/اللاتينية الفعلية بعيداً عن مفاتيح JSON
    words = re.findall(r"[\w\u0600-\u06FF]+", raw)
    return len(words)


class VaultExporter:
    def __init__(self, cfg_manager, db, log_fn=print):
        self.cfg_mgr = cfg_manager
        self.db = db
        self.log = log_fn

    def _split_novels_into_parts(self, novels, max_words_per_part):
        if not novels:
            return []
        parts = []
        current = []
        current_words = 0

        for n in novels:
            wc = _count_novel_sections_words(n)
            # قاعدة صارمة: لا يُقص أي عمل/رواية من منتصفها أبداً
            if current and (current_words + wc > max_words_per_part):
                parts.append(current)
                current = []
                current_words = 0
            current.append(n)
            current_words += wc

        if current:
            parts.append(current)
        return parts

    def _get_section_title(self, sec_id, default_title, lens_cfg):
        if sec_id == "system_laws":
            return lens_cfg.get("section_6_title", default_title)
        if sec_id == "micro_tactics":
            return lens_cfg.get("section_7_title", default_title)
        return default_title

    # ------------------------------------------------------------------
    # تصدير جزء واحد بصيغة Markdown مهيكلة لـ Google AI Studio
    # ------------------------------------------------------------------
    def _write_part_md(self, out_path, lens_cfg, part_idx, total_parts, part_novels):
        sections_meta = self.cfg_mgr.get_sections_order()
        lines = []
        lines.append(f"# {lens_cfg['display_name']} — الجزء {part_idx:02d} من {total_parts:02d}")
        lines.append(f"> مرجع منظم لـ AI Studio | عدد الروايات في هذا الجزء: {len(part_novels)}\n")

        # جدول الفهرسة الخاص بهذا الجزء
        lines.append("## فهرس روايات هذا الجزء")
        lines.append("| # | عنوان الرواية | المؤلف | السلسلة / المجلد | الوسوم | كلمات التحليل |")
        lines.append("|---|---|---|---|---|---|")
        for idx, n in enumerate(part_novels, 1):
            title = n.get("title") or n["file_name"]
            author = n.get("author") or "غير معروف"
            series = f"{n['series_name']} (م{n['volume_number']})" if n.get("series_name") else "مستقلة"
            tags = "، ".join(n.get("sub_tags", []))
            wc = _count_novel_sections_words(n)
            lines.append(f"| {idx} | {title} | {author} | {series} | {tags} | {wc:,} |")
        lines.append("\n---\n")

        for sm in sections_meta:
            sid = sm["id"]
            snum = sm["num"]
            stitle = self._get_section_title(sid, sm["title"], lens_cfg)
            lines.append(f"## القسم {snum}: {stitle}\n")

            for n in part_novels:
                ntitle = n.get("title") or n["file_name"]
                sec = n.get("sections", {})

                if sid == "philosophy_bank":
                    items = sec.get("section_1_philosophy", [])
                    if items:
                        lines.append(f"### [الرواية: {ntitle}]")
                        for i, it in enumerate(items, 1):
                            lines.append(f"{i}. **\"{it.get('quote', '')}\"** ({it.get('chapter_context', '')})")
                            lines.append(f"   - **المحور:** {it.get('theme', '')}")
                            lines.append(f"   - **القاعدة النفسية:** {it.get('psychological_rule', '')}")
                            lines.append(f"   - **الوظيفة السردية:** {it.get('narrative_function', '')}")
                        lines.append("")

                elif sid == "dialogue_engineering":
                    items = sec.get("section_2_dialogues", [])
                    if items:
                        lines.append(f"### [الرواية: {ntitle}]")
                        for it in items:
                            lines.append(f"#### {it.get('title', 'موقف حواري')} ({it.get('chapter_context', '')})")
                            lines.append(f"- **السطح المنطوق:** {it.get('spoken_surface', '')}")
                            lines.append(f"- **العمق الباطني:** {it.get('hidden_subtext', '')}")
                            lines.append(f"- **التكتيك ({it.get('tactic_name', '')}):** {it.get('tactical_breakdown', '')}\n")

                elif sid == "arc_structure":
                    arc = sec.get("section_3_arc_structure", {})
                    if arc:
                        lines.append(f"### [الرواية: {ntitle}]")
                        lines.append(f"- **الافتتاحية:** {arc.get('opening_hook', '')}")
                        for th in arc.get("parallel_threads", []):
                            lines.append(f"  - **خيط ({th.get('name', '')}):** {th.get('progression', '')}")
                        lines.append(f"- **ذروة التصادم:** {arc.get('climax_collision', '')}")
                        if arc.get("open_threads"):
                            lines.append(f"- **الخيوط المفتوحة:** {arc.get('open_threads', '')}")
                        lines.append("")

                elif sid == "foreshadowing":
                    items = sec.get("section_4_foreshadowing", [])
                    if items:
                        lines.append(f"### [الرواية: {ntitle}]")
                        for i, it in enumerate(items, 1):
                            lines.append(f"{i}. **{it.get('title', '')}**")
                            lines.append(f"   - **البذرة المبكرة:** {it.get('early_seed', '')}")
                            lines.append(f"   - **التمويه:** {it.get('camouflage_method', '')}")
                            lines.append(f"   - **التفجير/الحصاد:** {it.get('payoff_twist', '')}")
                        lines.append("")

                elif sid == "abstract_blueprints":
                    bp = sec.get("section_5_blueprint", {})
                    if bp:
                        lines.append(f"### [الرواية: {ntitle}]")
                        lines.append(f"- **المسار القياسي:** `{bp.get('summary_flow', '')}`")
                        for st in bp.get("stages", []):
                            lines.append(f"  - **مرحلة {st.get('stage_num', '')}: {st.get('stage_name', '')}** — {st.get('engineering', '')} | *التوجيه والكسر:* {st.get('expectation_vs_twist', '')}")
                        if bp.get("mutation_70_example"):
                            lines.append(f"- **تحوير 70%:** {bp.get('mutation_70_example', '')}")
                        lines.append("")

                elif sid == "system_laws":
                    sl = sec.get("section_6_system_laws", {})
                    if sl:
                        lines.append(f"### [الرواية: {ntitle}]")
                        for key, lbl in (
                            ("mechanics", "آليات العمل"),
                            ("costs_and_side_effects", "التكلفة والآثار الجانبية"),
                            ("weaknesses_and_balance", "نقاط الضعف والتوازن"),
                            ("resource_economy", "اقتصاد الموارد والندرة"),
                        ):
                            vals = sl.get(key, [])
                            if vals:
                                lines.append(f"- **{lbl}:**")
                                for v in vals:
                                    lines.append(f"  - {v}")
                        muts = sl.get("mutations_70", [])
                        if muts:
                            lines.append("- **تحوير الآليات 70%:**")
                            for m in muts:
                                lines.append(f"  - **{m.get('mutated_name', '')}** (عن: {m.get('original_name', '')}): {m.get('new_mechanism', '')} | *القيد القاتل:* {m.get('fatal_cost', '')}")
                        lines.append("")

                elif sid == "micro_tactics":
                    items = sec.get("section_7_micro_tactics", [])
                    if items:
                        lines.append(f"### [الرواية: {ntitle}]")
                        for it in items:
                            lines.append(f"#### {it.get('name', '')}")
                            lines.append(f"- **الموقف المرجعي:** {it.get('reference_scene', '')}")
                            lines.append(f"- **المعادلة المجردة:** `{it.get('abstract_equation', '')}`")
                            lines.append(f"- **التنفيذ:** {it.get('execution_steps', '')}")
                            lines.append(f"- **شرط النجاح:** {it.get('success_condition', '')} | **ثغرة الفشل:** {it.get('failure_risk', '')}\n")

                elif sid == "sensory_lexicon":
                    cats = sec.get("section_8_sensory_lexicon", [])
                    if cats:
                        lines.append(f"### [الرواية: {ntitle}]")
                        for cat in cats:
                            lines.append(f"#### {cat.get('category', '')}")
                            for it in cat.get("items", []):
                                lines.append(f"- **{it.get('title', '')}:** \"{it.get('quote', '')}\" — *القاعدة:* {it.get('stylistic_rule', '')}")
                        lines.append("")

                elif sid == "character_dna":
                    ch_block = sec.get("section_9_characters", {})
                    chars = ch_block.get("characters", [])
                    muts = ch_block.get("mutations_70", [])
                    if chars or muts:
                        lines.append(f"### [الرواية: {ntitle}]")
                        for c in chars:
                            lines.append(f"#### {c.get('name_and_title', '')}")
                            lines.append(f"- **دلالة الاسم:** {c.get('name_symbolism', '')}")
                            lines.append(f"- **القناع الخارجي:** {c.get('outer_mask', '')}")
                            lines.append(f"- **الدافع الخفي:** {c.get('hidden_motive', '')}")
                            lines.append(f"- **التناقض الداخلي:** {c.get('inner_contradiction', '')}")
                            lines.append(f"- **اللازمة المميزة:** {c.get('signature_habit', '')}")
                            lines.append(f"- **الخصائص ومسار التحول:** {c.get('physical_and_psych_arc', '')}\n")
                        if muts:
                            lines.append("#### شخصيات مولدة بتحوير 70%")
                            for m in muts:
                                lines.append(f"- **{m.get('new_name_and_title', '')}** (مستلهمة من: {m.get('inspired_by', '')} | {m.get('target_world', '')}): القناع: {m.get('outer_mask', '')} | الدافع: {m.get('hidden_motive', '')} | اللازمة: {m.get('signature_habit', '')} | الخصائص: {m.get('traits', '')}")
                        lines.append("")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    # ------------------------------------------------------------------
    # تصدير جزء واحد بصيغة DOCX نظيفة ومنسقة لـ Microsoft Word (RTL)
    # ------------------------------------------------------------------
    def _write_part_docx(self, out_path, lens_cfg, part_idx, total_parts, part_novels):
        sections_meta = self.cfg_mgr.get_sections_order()
        doc = _configure_arabic_docx()

        _add_rtl_heading(doc, f"{lens_cfg['display_name']} — الجزء {part_idx:02d} من {total_parts:02d}", level=1)
        _add_rtl_paragraph(doc, "عدد الروايات في هذا الجزء", str(len(part_novels)))

        _add_rtl_heading(doc, "فهرس روايات هذا الجزء", level=2)
        rows = []
        for idx, n in enumerate(part_novels, 1):
            title = n.get("title") or n["file_name"]
            author = n.get("author") or "غير معروف"
            series = f"{n['series_name']} (م{n['volume_number']})" if n.get("series_name") else "مستقلة"
            tags = "، ".join(n.get("sub_tags", []))
            wc = _count_novel_sections_words(n)
            rows.append([str(idx), title, author, series, tags, f"{wc:,}"])
        _fill_rtl_table(doc, ["#", "عنوان الرواية", "المؤلف", "السلسلة / المجلد", "الوسوم", "كلمات التحليل"], rows)

        for sm in sections_meta:
            sid = sm["id"]
            snum = sm["num"]
            stitle = self._get_section_title(sid, sm["title"], lens_cfg)
            doc.add_page_break()
            _add_rtl_heading(doc, f"القسم {snum}: {stitle}", level=1)

            for n in part_novels:
                ntitle = n.get("title") or n["file_name"]
                sec = n.get("sections", {})

                if sid == "philosophy_bank":
                    items = sec.get("section_1_philosophy", [])
                    if items:
                        _add_rtl_heading(doc, f"من رواية: {ntitle}", level=2)
                        for i, it in enumerate(items, 1):
                            _add_rtl_paragraph(doc, f"{i}) الاقتباس ({it.get('chapter_context', '')})", f"\"{it.get('quote', '')}\"")
                            _add_rtl_paragraph(doc, "المحور", it.get("theme", ""), bullet=True)
                            _add_rtl_paragraph(doc, "القاعدة النفسية", it.get("psychological_rule", ""), bullet=True)
                            _add_rtl_paragraph(doc, "الوظيفة السردية", it.get("narrative_function", ""), bullet=True)

                elif sid == "dialogue_engineering":
                    items = sec.get("section_2_dialogues", [])
                    if items:
                        _add_rtl_heading(doc, f"من رواية: {ntitle}", level=2)
                        for it in items:
                            _add_rtl_heading(doc, f"{it.get('title', 'موقف حواري')} ({it.get('chapter_context', '')})", level=3)
                            _add_rtl_paragraph(doc, "السطح المنطوق", it.get("spoken_surface", ""), bullet=True)
                            _add_rtl_paragraph(doc, "العمق الباطني", it.get("hidden_subtext", ""), bullet=True)
                            _add_rtl_paragraph(doc, f"التكتيك ({it.get('tactic_name', '')})", it.get("tactical_breakdown", ""), bullet=True)

                elif sid == "arc_structure":
                    arc = sec.get("section_3_arc_structure", {})
                    if arc:
                        _add_rtl_heading(doc, f"من رواية: {ntitle}", level=2)
                        _add_rtl_paragraph(doc, "الافتتاحية والخطاف", arc.get("opening_hook", ""))
                        for th in arc.get("parallel_threads", []):
                            _add_rtl_paragraph(doc, f"خيط ({th.get('name', '')})", th.get("progression", ""), bullet=True)
                        _add_rtl_paragraph(doc, "ذروة التصادم", arc.get("climax_collision", ""))
                        if arc.get("open_threads"):
                            _add_rtl_paragraph(doc, "الخيوط المفتوحة", arc.get("open_threads", ""))

                elif sid == "foreshadowing":
                    items = sec.get("section_4_foreshadowing", [])
                    if items:
                        _add_rtl_heading(doc, f"من رواية: {ntitle}", level=2)
                        for i, it in enumerate(items, 1):
                            _add_rtl_heading(doc, f"{i}) {it.get('title', '')}", level=3)
                            _add_rtl_paragraph(doc, "البذرة المبكرة", it.get("early_seed", ""), bullet=True)
                            _add_rtl_paragraph(doc, "التمويه", it.get("camouflage_method", ""), bullet=True)
                            _add_rtl_paragraph(doc, "التفجير والحصاد", it.get("payoff_twist", ""), bullet=True)

                elif sid == "abstract_blueprints":
                    bp = sec.get("section_5_blueprint", {})
                    if bp:
                        _add_rtl_heading(doc, f"من رواية: {ntitle}", level=2)
                        _add_rtl_paragraph(doc, "المسار القياسي", bp.get("summary_flow", ""))
                        for st in bp.get("stages", []):
                            _add_rtl_paragraph(
                                doc,
                                f"المرحلة {st.get('stage_num', '')}: {st.get('stage_name', '')}",
                                f"{st.get('engineering', '')} — التوجيه والكسر: {st.get('expectation_vs_twist', '')}",
                                bullet=True
                            )
                        if bp.get("mutation_70_example"):
                            _add_rtl_paragraph(doc, "التطبيق المحوّر 70%", bp.get("mutation_70_example", ""))

                elif sid == "system_laws":
                    sl = sec.get("section_6_system_laws", {})
                    if sl:
                        _add_rtl_heading(doc, f"من رواية: {ntitle}", level=2)
                        for key, lbl in (
                            ("mechanics", "آليات العمل"),
                            ("costs_and_side_effects", "التكلفة والآثار الجانبية"),
                            ("weaknesses_and_balance", "نقاط الضعف والتوازن"),
                            ("resource_economy", "اقتصاد الموارد والندرة"),
                        ):
                            vals = sl.get(key, [])
                            if vals:
                                _add_rtl_heading(doc, lbl, level=3)
                                for v in vals:
                                    _add_rtl_paragraph(doc, "", v, bullet=True)
                        muts = sl.get("mutations_70", [])
                        if muts:
                            _add_rtl_heading(doc, "تحوير الآليات 70%", level=3)
                            for m in muts:
                                _add_rtl_paragraph(
                                    doc,
                                    f"{m.get('mutated_name', '')} (عن: {m.get('original_name', '')})",
                                    f"{m.get('new_mechanism', '')} — القيد القاتل: {m.get('fatal_cost', '')}",
                                    bullet=True
                                )

                elif sid == "micro_tactics":
                    items = sec.get("section_7_micro_tactics", [])
                    if items:
                        _add_rtl_heading(doc, f"من رواية: {ntitle}", level=2)
                        for it in items:
                            _add_rtl_heading(doc, it.get("name", ""), level=3)
                            _add_rtl_paragraph(doc, "الموقف المرجعي", it.get("reference_scene", ""), bullet=True)
                            _add_rtl_paragraph(doc, "المعادلة المجردة", it.get("abstract_equation", ""), bullet=True)
                            _add_rtl_paragraph(doc, "خطوات التنفيذ", it.get("execution_steps", ""), bullet=True)
                            _add_rtl_paragraph(doc, "شرط النجاح", it.get("success_condition", ""), bullet=True)
                            _add_rtl_paragraph(doc, "ثغرة الفشل", it.get("failure_risk", ""), bullet=True)

                elif sid == "sensory_lexicon":
                    cats = sec.get("section_8_sensory_lexicon", [])
                    if cats:
                        _add_rtl_heading(doc, f"من رواية: {ntitle}", level=2)
                        for cat in cats:
                            _add_rtl_heading(doc, cat.get("category", ""), level=3)
                            for it in cat.get("items", []):
                                _add_rtl_paragraph(
                                    doc,
                                    it.get("title", ""),
                                    f"\"{it.get('quote', '')}\" — القاعدة الأسلوبية: {it.get('stylistic_rule', '')}",
                                    bullet=True
                                )

                elif sid == "character_dna":
                    ch_block = sec.get("section_9_characters", {})
                    chars = ch_block.get("characters", [])
                    muts = ch_block.get("mutations_70", [])
                    if chars or muts:
                        _add_rtl_heading(doc, f"من رواية: {ntitle}", level=2)
                        for c in chars:
                            _add_rtl_heading(doc, c.get("name_and_title", ""), level=3)
                            _add_rtl_paragraph(doc, "دلالة الاسم", c.get("name_symbolism", ""), bullet=True)
                            _add_rtl_paragraph(doc, "القناع الخارجي", c.get("outer_mask", ""), bullet=True)
                            _add_rtl_paragraph(doc, "الدافع الخفي", c.get("hidden_motive", ""), bullet=True)
                            _add_rtl_paragraph(doc, "التناقض الداخلي", c.get("inner_contradiction", ""), bullet=True)
                            _add_rtl_paragraph(doc, "اللازمة المميزة", c.get("signature_habit", ""), bullet=True)
                            _add_rtl_paragraph(doc, "الخصائص ومسار التحول", c.get("physical_and_psych_arc", ""), bullet=True)
                        if muts:
                            _add_rtl_heading(doc, "شخصيات مولدة بتحوير 70%", level=3)
                            for m in muts:
                                _add_rtl_paragraph(
                                    doc,
                                    f"{m.get('new_name_and_title', '')} (عن: {m.get('inspired_by', '')})",
                                    f"العالم: {m.get('target_world', '')} | القناع: {m.get('outer_mask', '')} | الدافع: {m.get('hidden_motive', '')} | اللازمة: {m.get('signature_habit', '')} | الخصائص: {m.get('traits', '')}",
                                    bullet=True
                                )

        doc.save(out_path)

    # ------------------------------------------------------------------
    # تصدير القسم العاشر: 00_الخلاصة_التوليفية_الشاملة (.md و .docx)
    # ------------------------------------------------------------------
    def _export_meta_synthesis(self, lens_dir, lens_cfg, syn_data):
        md_path = os.path.join(lens_dir, "00_الخلاصة_التوليفية_الشاملة.md")
        docx_path = os.path.join(lens_dir, "00_الخلاصة_التوليفية_الشاملة.docx")

        # 1. ملف MD
        md = [
            f"# القسم 10: الخلاصة التوليفية الشاملة — {lens_cfg['display_name']}",
            f"\n## النظرة البانورامية\n{syn_data.get('lens_overview', '')}\n",
            "## أولاً: القوانين الكبرى المشتركة"
        ]
        for i, law in enumerate(syn_data.get("grand_shared_laws", []), 1):
            novs = "، ".join(law.get("documented_novels", []))
            md.append(f"{i}. **{law.get('law_title', '')}:** {law.get('explanation', '')}\n   - *الروايات الموثقة:* {novs}")

        md.append("\n## ثانياً: التوليفات المبتكرة الجديدة")
        for i, inv in enumerate(syn_data.get("innovative_syntheses", []), 1):
            novs = "، ".join(inv.get("inspired_by", []))
            md.append(
                f"{i}. **{inv.get('synthesis_name', '')}**\n"
                f"   - *المعادلة:* `{inv.get('formula', '')}`\n"
                f"   - *التطبيق العملي للكاتب:* {inv.get('practical_application_for_writers', '')}\n"
                f"   - *ملهمة من:* {novs}"
            )

        md.append("\n## ثالثاً: تقصي الاختلاف والتنوع والحالات النادرة")
        for i, div in enumerate(syn_data.get("diversity_and_outliers_audit", []), 1):
            novs = "، ".join(div.get("documented_novels", []))
            md.append(f"{i}. **{div.get('dimension', '')}:** {div.get('spectrum_and_rare_cases', '')}\n   - *الروايات:* {novs}")

        md.append("\n## رابعاً: أمثلة مركّزة موثّقة بالروايات")
        for i, ex in enumerate(syn_data.get("concentrated_master_examples", []), 1):
            md.append(f"{i}. **[{ex.get('category', '')}] {ex.get('title', '')}** (الرواية: {ex.get('source_novel', '')})\n   - {ex.get('breakdown', '')}")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md))

        # 2. ملف DOCX
        doc = _configure_arabic_docx()
        _add_rtl_heading(doc, f"القسم 10: الخلاصة التوليفية الشاملة — {lens_cfg['display_name']}", level=1)
        _add_rtl_heading(doc, "النظرة البانورامية", level=2)
        _add_rtl_paragraph(doc, "", syn_data.get("lens_overview", ""))

        _add_rtl_heading(doc, "أولاً: القوانين الكبرى المشتركة", level=2)
        for i, law in enumerate(syn_data.get("grand_shared_laws", []), 1):
            novs = "، ".join(law.get("documented_novels", []))
            _add_rtl_paragraph(doc, f"{i}) {law.get('law_title', '')}", law.get("explanation", ""))
            _add_rtl_paragraph(doc, "الروايات الموثقة", novs, bullet=True)

        _add_rtl_heading(doc, "ثانياً: التوليفات المبتكرة الجديدة", level=2)
        for i, inv in enumerate(syn_data.get("innovative_syntheses", []), 1):
            novs = "، ".join(inv.get("inspired_by", []))
            _add_rtl_heading(doc, f"{i}) {inv.get('synthesis_name', '')}", level=3)
            _add_rtl_paragraph(doc, "المعادلة", inv.get("formula", ""), bullet=True)
            _add_rtl_paragraph(doc, "التطبيق العملي للكاتب", inv.get("practical_application_for_writers", ""), bullet=True)
            _add_rtl_paragraph(doc, "ملهمة من", novs, bullet=True)

        _add_rtl_heading(doc, "ثالثاً: تقصي الاختلاف والتنوع والحالات النادرة", level=2)
        for i, div in enumerate(syn_data.get("diversity_and_outliers_audit", []), 1):
            novs = "، ".join(div.get("documented_novels", []))
            _add_rtl_paragraph(doc, f"{i}) {div.get('dimension', '')}", div.get("spectrum_and_rare_cases", ""))
            _add_rtl_paragraph(doc, "الروايات", novs, bullet=True)

        _add_rtl_heading(doc, "رابعاً: أمثلة مركّزة موثّقة بالروايات", level=2)
        for i, ex in enumerate(syn_data.get("concentrated_master_examples", []), 1):
            _add_rtl_paragraph(
                doc,
                f"{i}) [{ex.get('category', '')}] {ex.get('title', '')} ({ex.get('source_novel', '')})",
                ex.get("breakdown", "")
            )

        doc.save(docx_path)
        return [md_path, docx_path]

    # ------------------------------------------------------------------
    # تصدير جميع العدسات + التقسيم التلقائي + تنظيف الأجزاء القديمة
    # ------------------------------------------------------------------
    def export_all_lenses(self, lens_filter=None):
        paths = self.cfg_mgr.get_paths()
        lenses = self.cfg_mgr.get_lenses()
        max_words = int(self.cfg_mgr.config.get("export_max_words_per_part", 350000))
        exported_map = {}

        target_lenses = [lens_filter] if lens_filter else list(lenses.keys())

        for lid in target_lenses:
            if lid not in lenses:
                continue
            novels = self.db.get_distilled_novels_with_analyses(lid)
            if not novels:
                continue

            lens_cfg = lenses[lid]
            folder_name = _safe_filename(lens_cfg["folder_name"])
            lens_dir = os.path.join(paths["exports"], folder_name)
            os.makedirs(lens_dir, exist_ok=True)

            # تنظيف أي ملفات أجزاء قديمة داخل مجلد العدسة قبل إعادة التوليد
            for fname in os.listdir(lens_dir):
                if "_الجزء_" in fname and (fname.endswith(".md") or fname.endswith(".docx")):
                    os.remove(os.path.join(lens_dir, fname))

            parts = self._split_novels_into_parts(novels, max_words)
            total_parts = len(parts)
            created_files = []

            for p_idx, p_novels in enumerate(parts, 1):
                md_file = os.path.join(lens_dir, f"{folder_name}_الجزء_{p_idx:02d}.md")
                docx_file = os.path.join(lens_dir, f"{folder_name}_الجزء_{p_idx:02d}.docx")
                self._write_part_md(md_file, lens_cfg, p_idx, total_parts, p_novels)
                self._write_part_docx(docx_file, lens_cfg, p_idx, total_parts, p_novels)
                created_files.extend([md_file, docx_file])

            # تصدير القسم 10 إن توفر في قاعدة البيانات
            meta_row = self.db.get_meta_final(lid)
            if meta_row and meta_row.get("synthesis_json"):
                syn_data = json.loads(meta_row["synthesis_json"])
                created_files.extend(self._export_meta_synthesis(lens_dir, lens_cfg, syn_data))

            exported_map[lid] = created_files
            self.log(f"[تصدير] {lens_cfg['display_name']} --> {total_parts} جزء ({len(novels)} رواية) في {lens_dir}")

        return exported_map

    def create_backup_snapshot(self, keep_latest=5):
        paths = self.cfg_mgr.get_paths()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.join(paths["backups"], f"NovelStudio_Backup_{ts}.zip")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fpath in (paths["db"], self.cfg_mgr.config_path, self.cfg_mgr.lenses_path):
                if os.path.exists(fpath):
                    zf.write(fpath, arcname=os.path.basename(fpath))
            if os.path.isdir(paths["exports"]):
                for root_d, _, files in os.walk(paths["exports"]):
                    for fn in files:
                        full = os.path.join(root_d, fn)
                        rel = os.path.relpath(full, paths["root"])
                        zf.write(full, arcname=rel)

        # الاحتفاظ بآخر 5 نسخ احتياطية فقط
        backups = sorted(
            [os.path.join(paths["backups"], f) for f in os.listdir(paths["backups"]) if f.endswith(".zip")],
            key=os.path.getmtime,
            reverse=True
        )
        for old in backups[keep_latest:]:
            os.remove(old)

        self.log(f"[نسخة احتياطية] تم حفظ: {os.path.basename(zip_path)}")
        return zip_path