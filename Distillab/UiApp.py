import json
import os
import shutil

import gradio as gr

from core.config_manager import ConfigManager
from core.database import LibraryDB
from core.exporters import VaultExporter
from core.pipeline import NovelPipeline


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
cfg_mgr = ConfigManager(BASE_DIR)


def _get_runtime():
    cfg_mgr.load_config()
    paths = cfg_mgr.get_paths()
    db = LibraryDB(paths["db"])
    logs = []

    def log_fn(msg):
        logs.append(str(msg))
        print(msg)

    pipeline = NovelPipeline(cfg_mgr, db, log_fn=log_fn)
    exporter = VaultExporter(cfg_mgr, db, log_fn=log_fn)
    return paths, db, pipeline, exporter, logs


def ui_get_stats():
    _, db, _, _, _ = _get_runtime()
    st = db.get_stats()
    lenses = cfg_mgr.get_lenses()
    lines = [
        f"إجمالي الروايات المسجلة: {st['total']}",
        f"بانتظار الفرز (scanned): {st['by_status'].get('scanned', 0)}",
        f"مصنفة وجاهزة للتقطير (scouted): {st['by_status'].get('scouted', 0)}",
        f"قيد الاستئناف (chunking): {st['by_status'].get('chunking', 0)}",
        f"مكتملة (distilled): {st['by_status'].get('distilled', 0)}",
        f"أخطاء تحتاج مراجعة (error): {st['by_status'].get('error', 0)}",
        "--- توزيع العدسات ---"
    ]
    for lid, cnt in st["by_lens"].items():
        lname = lenses.get(lid, {}).get("display_name", lid)
        lines.append(f"• {lname}: {cnt}")
    return "\n".join(lines)


def ui_upload_to_inbox(files):
    if not files:
        return "لم يتم اختيار ملفات."
    paths, _, _, _, _ = _get_runtime()
    saved = []
    for f in files:
        src = f.name if hasattr(f, "name") else str(f)
        dest = os.path.join(paths["inbox"], os.path.basename(src))
        shutil.copy2(src, dest)
        saved.append(os.path.basename(src))
    return f"تم رفع {len(saved)} ملف بنجاح إلى صندوق الوارد:\n" + "\n".join(saved)


def ui_scan_inbox():
    _, _, pipeline, _, logs = _get_runtime()
    pipeline.scan_inbox()
    return "\n".join(logs), ui_get_stats()


def ui_run_scout(limit):
    _, _, pipeline, _, logs = _get_runtime()
    pipeline.run_scout(max_items=int(limit or 0))
    return "\n".join(logs), ui_get_stats()


def ui_run_distill(limit, lens_choice):
    _, _, pipeline, _, logs = _get_runtime()
    lf = None if lens_choice == "الكل" else lens_choice
    pipeline.run_distillation(max_items=int(limit or 0), lens_filter=lf)
    return "\n".join(logs), ui_get_stats()


def ui_run_meta(lens_choice):
    _, _, pipeline, _, logs = _get_runtime()
    lf = None if lens_choice == "الكل" else lens_choice
    pipeline.run_meta_synthesis(lens_filter=lf)
    return "\n".join(logs), ui_get_stats()


def ui_run_export_and_cleanup(lens_choice):
    _, _, pipeline, exporter, logs = _get_runtime()
    lf = None if lens_choice == "الكل" else lens_choice
    exp_map = exporter.export_all_lenses(lens_filter=lf)
    pipeline.run_cleanup_gate(exp_map)
    if cfg_mgr.config.get("auto_backup_after_run", True):
        exporter.create_backup_snapshot()
    return "\n".join(logs), ui_get_stats()


def ui_run_full_cycle(limit, lens_choice):
    _, _, pipeline, exporter, logs = _get_runtime()
    lf = None if lens_choice == "الكل" else lens_choice
    pipeline.scan_inbox()
    pipeline.run_scout(max_items=int(limit or 0))
    pipeline.run_distillation(max_items=int(limit or 0), lens_filter=lf)
    pipeline.run_meta_synthesis(lens_filter=lf)
    exp_map = exporter.export_all_lenses(lens_filter=lf)
    pipeline.run_cleanup_gate(exp_map)
    if cfg_mgr.config.get("auto_backup_after_run", True):
        exporter.create_backup_snapshot()
    return "\n".join(logs), ui_get_stats()


def ui_list_library():
    _, db, _, _, _ = _get_runtime()
    rows = db.list_novels()
    table = []
    for r in rows:
        table.append([
            r["id"],
            r.get("title") or r["file_name"],
            r.get("series_name") or "-",
            r.get("volume_number") or 0,
            r.get("primary_lens") or "-",
            f"{r.get('word_count', 0):,}",
            r.get("status"),
            "نعم" if r.get("cleanup_done") else "لا",
            (r.get("error_msg") or "")[:60]
        ])
    return table


def ui_search_vault(keyword):
    kw = (keyword or "").strip()
    if not kw:
        return "اكتب كلمة بحث (مثل: السم، حجة غياب، تلاعب، خدعة)."
    _, db, _, _, _ = _get_runtime()
    lenses = cfg_mgr.get_lenses()
    hits = []
    for lid in lenses.keys():
        for n in db.get_distilled_novels_with_analyses(lid):
            title = n.get("title") or n["file_name"]
            sec = n["sections"]
            blob = json.dumps(sec, ensure_ascii=False)
            if kw in blob:
                # نبحث داخل الأقسام لعرض مقتطفات مركزة
                for q in sec.get("section_1_philosophy", []):
                    if kw in json.dumps(q, ensure_ascii=False):
                        hits.append(f"[{title} | مقولة] \"{q.get('quote', '')}\" — {q.get('psychological_rule', '')}")
                for d in sec.get("section_2_dialogues", []):
                    if kw in json.dumps(d, ensure_ascii=False):
                        hits.append(f"[{title} | حوار] {d.get('title', '')} ({d.get('tactic_name', '')}): {d.get('tactical_breakdown', '')}")
                for f in sec.get("section_4_foreshadowing", []):
                    if kw in json.dumps(f, ensure_ascii=False):
                        hits.append(f"[{title} | بذرة] {f.get('title', '')}: {f.get('early_seed', '')} --> {f.get('payoff_twist', '')}")
                for t in sec.get("section_7_micro_tactics", []):
                    if kw in json.dumps(t, ensure_ascii=False):
                        hits.append(f"[{title} | تكتيك] {t.get('name', '')}: {t.get('abstract_equation', '')}")
    if not hits:
        return f"لم يتم العثور على نتائج للكلمة: {kw}"
    return "\n\n".join(hits[:40])


def ui_reset_error_novels():
    _, db, _, _, _ = _get_runtime()
    errs = db.list_novels(status="error")
    cnt = 0
    for r in errs:
        new_st = "scouted" if r.get("primary_lens") else "scanned"
        db.set_novel_status(r["id"], new_st, "")
        cnt += 1
    return f"تمت إعادة تعيين {cnt} رواية للمحاولة مجدداً.", ui_list_library()


def ui_load_settings():
    cfg = cfg_mgr.config
    pname, pcfg = cfg_mgr.get_active_provider_cfg()
    return (
        cfg.get("project_root_dir", ""),
        "\n".join(cfg.get("extra_inbox_dirs", [])),
        pname,
        pcfg.get("base_url", ""),
        pcfg.get("scout_model", ""),
        pcfg.get("distill_model", ""),
        pcfg.get("meta_model", ""),
        "\n".join(pcfg.get("api_keys", [])),
        float(pcfg.get("min_delay_sec", 6.5)),
        cfg.get("chunk_mode", "smart_chunks"),
        int(cfg.get("chunk_max_words", 45000)),
        int(cfg.get("export_max_words_per_part", 350000)),
        int(cfg.get("meta_batch_size", 8)),
        cfg.get("post_complete_action", "archive_compressed"),
        bool(cfg.get("confirm_permanent_delete", False)),
        cfg.get("custom_mutation_target", "")
    )


def ui_save_settings(
    root_dir, extra_dirs_txt, active_prov, base_url,
    scout_m, distill_m, meta_m, keys_txt, min_delay,
    chunk_mode, chunk_max_w, export_max_w, meta_b_size,
    cleanup_act, confirm_del, custom_mut
):
    cfg = cfg_mgr.config
    cfg["project_root_dir"] = root_dir.strip()
    cfg["extra_inbox_dirs"] = [ln.strip() for ln in (extra_dirs_txt or "").splitlines() if ln.strip()]
    cfg["active_provider"] = active_prov
    pcfg = cfg["providers"][active_prov]
    pcfg["base_url"] = base_url.strip()
    pcfg["scout_model"] = scout_m.strip()
    pcfg["distill_model"] = distill_m.strip()
    pcfg["meta_model"] = meta_m.strip()
    pcfg["api_keys"] = [ln.strip() for ln in (keys_txt or "").splitlines() if ln.strip()]
    pcfg["min_delay_sec"] = float(min_delay)

    cfg["chunk_mode"] = chunk_mode
    cfg["chunk_max_words"] = int(chunk_max_w)
    cfg["export_max_words_per_part"] = int(export_max_w)
    cfg["meta_batch_size"] = int(meta_b_size)
    cfg["post_complete_action"] = cleanup_act
    cfg["confirm_permanent_delete"] = bool(confirm_del)
    cfg["custom_mutation_target"] = (custom_mut or "").strip()

    cfg_mgr.save_config(cfg)
    cfg_mgr.get_paths()
    return "تم حفظ الإعدادات وتحديث المسارات بنجاح!"


def ui_list_downloadable_files():
    paths, _, _, _, _ = _get_runtime()
    found = []
    for folder in (paths["exports"], paths["backups"]):
        if os.path.isdir(folder):
            for r, _, fs in os.walk(folder):
                for fn in sorted(fs):
                    if fn.endswith((".md", ".docx", ".zip")):
                        found.append(os.path.join(r, fn))
    return gr.Dropdown(choices=found, value=found[0] if found else None)


def ui_prepare_download(file_path):
    if file_path and os.path.exists(file_path):
        return file_path
    return None


def build_ui():
    lens_choices = ["الكل"] + list(cfg_mgr.get_lenses().keys())

    with gr.Blocks(title="NovelStudio Cloud — استوديو التحليل والتقطير") as demo:
        gr.Markdown("# NovelStudio Cloud\n### نظام التحليل المعماري وتقطير الروايات بالذكاء الاصطناعي (DOCX + MD)")

        with gr.Tab("1. التشغيل والمتابعة"):
            with gr.Row():
                limit_in = gr.Number(label="حد الروايات في هذه الجلسة (0 = الكل)", value=10, precision=0)
                lens_in = gr.Dropdown(label="العدسة المستهدفة", choices=lens_choices, value="الكل")

            with gr.Row():
                btn_full = gr.Button("🚀 تشغيل دورة كاملة (مسح + فرز + تقطير + قسم 10 + تصدير)", variant="primary")

            with gr.Row():
                btn_scan = gr.Button("1️⃣ مسح صندوق الوارد")
                btn_scout = gr.Button("2️⃣ فرز ذكي")
                btn_distill = gr.Button("3️⃣ تقطير / استئناف")
                btn_meta = gr.Button("4️⃣ القسم 10 (توليف هرمي)")
                btn_export = gr.Button("5️⃣ تصدير + تنظيف + نسخة احتياطية")

            with gr.Row():
                log_box = gr.Textbox(label="سجل العمليات المباشر", lines=16, interactive=False)
                stats_box = gr.Textbox(label="إحصائيات المكتبة", value=ui_get_stats, lines=16, interactive=False)

            btn_scan.click(ui_scan_inbox, outputs=[log_box, stats_box])
            btn_scout.click(ui_run_scout, inputs=[limit_in], outputs=[log_box, stats_box])
            btn_distill.click(ui_run_distill, inputs=[limit_in, lens_in], outputs=[log_box, stats_box])
            btn_meta.click(ui_run_meta, inputs=[lens_in], outputs=[log_box, stats_box])
            btn_export.click(ui_run_export_and_cleanup, inputs=[lens_in], outputs=[log_box, stats_box])
            btn_full.click(ui_run_full_cycle, inputs=[limit_in, lens_in], outputs=[log_box, stats_box])

        with gr.Tab("2. رفع الروايات (Inbox)"):
            up_files = gr.File(label="ارفع ملفات EPUB / PDF / DOCX / TXT من الهاتف أو الكمبيوتر", file_count="multiple")
            btn_up = gr.Button("رفع إلى Google Drive (_Inbox_Raw)")
            up_status = gr.Textbox(label="حالة الرفع", lines=5)
            btn_up.click(ui_upload_to_inbox, inputs=[up_files], outputs=[up_status])

        with gr.Tab("3. المكتبة والبحث"):
            with gr.Row():
                btn_refresh_lib = gr.Button("🔄 تحديث الجدول")
                btn_retry_err = gr.Button("♻️ إعادة تفعيل الروايات المتعطلة (Error)")
            lib_table = gr.Dataframe(
                headers=["ID", "العنوان", "السلسلة", "مجلد", "العدسة", "الكلمات", "الحالة", "تنظيف", "ملاحظة"],
                value=ui_list_library,
                interactive=False
            )
            err_msg = gr.Textbox(label="حالة الإجراء", lines=1)
            btn_refresh_lib.click(ui_list_library, outputs=[lib_table])
            btn_retry_err.click(ui_reset_error_novels, outputs=[err_msg, lib_table])

            gr.Markdown("### بحث متقاطع عبر جميع الروايات المحللة")
            with gr.Row():
                search_kw = gr.Textbox(label="كلمة البحث (بدون API)", placeholder="مثال: السم، حجة غياب، ابتزاز، قناع...")
                btn_search = gr.Button("🔍 بحث")
            search_res = gr.Textbox(label="نتائج البحث", lines=12)
            btn_search.click(ui_search_vault, inputs=[search_kw], outputs=[search_res])

        with gr.Tab("4. الإعدادات والمفاتيح والنماذج"):
            init_vals = ui_load_settings()
            s_root = gr.Textbox(label="مسار المشروع على Drive", value=init_vals[0])
            s_extra = gr.Textbox(label="مجلدات وارد إضافية (مسار بكل سطر — لمشاركة حسابات أخرى)", value=init_vals[1], lines=2)
            with gr.Row():
                s_prov = gr.Dropdown(label="المزود النشط", choices=list(cfg_mgr.config["providers"].keys()), value=init_vals[2])
                s_url = gr.Textbox(label="رابط Base URL للمزود", value=init_vals[3])
            with gr.Row():
                s_m_scout = gr.Textbox(label="نموذج الفرز (Scout)", value=init_vals[4])
                s_m_dist = gr.Textbox(label="نموذج التقطير (Distill)", value=init_vals[5])
                s_m_meta = gr.Textbox(label="نموذج القسم 10 (Meta)", value=init_vals[6])
            s_keys = gr.Textbox(label="مفاتيح الـ API (مفتاح في كل سطر للتدوير التلقائي)", value=init_vals[7], lines=4, type="password")
            with gr.Row():
                s_delay = gr.Number(label="الفاصل الزمني بين الطلبات (ثانية)", value=init_vals[8])
                s_cmode = gr.Dropdown(label="وضع السياق", choices=["smart_chunks", "full_novel"], value=init_vals[9])
                s_cwords = gr.Number(label="حد المقطع بالكلمات (للمجاني)", value=init_vals[10], precision=0)
            with gr.Row():
                s_exp_w = gr.Number(label="حد التقسيم التلقائي للتصدير (كلمة)", value=init_vals[11], precision=0)
                s_meta_b = gr.Number(label="عدد الروايات في حزمة القسم 10", value=init_vals[12], precision=0)
                s_mut = gr.Textbox(label="هدف التحوير 70% المخصص (اختياري)", value=init_vals[15])
            with gr.Row():
                s_clean = gr.Dropdown(
                    label="إجراء ما بعد الاكتمال وبوابة التحقق",
                    choices=["archive_compressed", "move_to_trash", "permanent_delete", "keep"],
                    value=init_vals[13]
                )
                s_conf_del = gr.Checkbox(label="تأكيد تفعيل الحذف النهائي (مطلوب فقط لخيار permanent_delete)", value=init_vals[14])

            btn_save_cfg = gr.Button("💾 حفظ الإعدادات", variant="primary")
            cfg_status = gr.Textbox(label="الحالة", lines=1)
            btn_save_cfg.click(
                ui_save_settings,
                inputs=[s_root, s_extra, s_prov, s_url, s_m_scout, s_m_dist, s_m_meta, s_keys, s_delay, s_cmode, s_cwords, s_exp_w, s_meta_b, s_clean, s_conf_del, s_mut],
                outputs=[cfg_status]
            )

        with gr.Tab("5. التحميل والنسخ الاحتياطي"):
            btn_ref_dl = gr.Button("🔄 جلب قائمة الملفات المُصدّرة والنسخ الاحتياطية")
            dl_drop = gr.Dropdown(label="اختر ملفاً لتنزيله (DOCX / MD / Backup ZIP)", choices=[])
            btn_dl = gr.Button("⬇️ تجهيز للتنزيل")
            dl_file = gr.File(label="الملف الجاهز")
            btn_ref_dl.click(ui_list_downloadable_files, outputs=[dl_drop])
            btn_dl.click(ui_prepare_download, inputs=[dl_drop], outputs=[dl_file])

    return demo


if __name__ == "__main__":
    app = build_ui()
    in_colab = "COLAB_RELEASE_TAG" in os.environ or os.path.exists("/content/drive")
    use_share = in_colab or os.environ.get("GRADIO_SHARE", "0") == "1"
    app.queue().launch(share=use_share, debug=False)