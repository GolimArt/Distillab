import inspect
import json
import os
import re
import shutil

import gradio as gr

from core.cloud_sync import GDriveClient, HFDatasetSync
from core.config_manager import ConfigManager
from core.database import LibraryDB
from core.exporters import VaultExporter
from core.pipeline import NovelPipeline
from core.readers import safe_unique_dest, scan_inbox_files


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
cfg_mgr = ConfigManager(BASE_DIR)
hf_sync = HFDatasetSync(log_fn=print)
gdrive_api = GDriveClient(log_fn=print)

RTL_STYLE_HTML = """
<style>
.gradio-container {
    direction: rtl !important;
    text-align: right !important;
    font-family: "Segoe UI", Tahoma, Arial, sans-serif !important;
}
.gradio-container input, .gradio-container textarea, .gradio-container select {
    text-align: right !important;
}
table {
    direction: rtl !important;
}
th, td {
    text-align: right !important;
}
</style>
"""


def _is_colab_mounted():
    return "COLAB_RELEASE_TAG" in os.environ or os.path.exists("/content/drive/MyDrive")


def _init_environment():
    if _is_colab_mounted():
        default_root = "/content/drive/MyDrive/Distillab_Cloud"
    else:
        default_root = os.environ.get("DISTILLAB_DATA_DIR", os.path.join(BASE_DIR, "Distillab_Data"))

    if not os.path.exists(cfg_mgr.config_path):
        cfg_mgr.config["project_root_dir"] = default_root
        cfg_mgr.save_config()

    hf_sync.pull_data(cfg_mgr.config.get("project_root_dir", default_root), BASE_DIR)
    cfg_mgr.load_config()

    # تأمين المسار عند النقل من Colab إلى Hugging Face
    if not _is_colab_mounted() and cfg_mgr.config.get("project_root_dir", "").startswith("/content/drive"):
        cfg_mgr.config["project_root_dir"] = default_root
        cfg_mgr.save_config()

    # تعبئة مفاتيح الـ API تلقائياً من Hugging Face Secrets إن لم تُحفظ بعد في الإعدادات
    env_gemini = [k.strip() for k in re.split(r"[,\n]+", os.environ.get("GEMINI_API_KEYS", "")) if k.strip()]
    if env_gemini and not cfg_mgr.config["providers"]["gemini"].get("api_keys"):
        cfg_mgr.config["providers"]["gemini"]["api_keys"] = env_gemini
        cfg_mgr.save_config()

    env_openai = [k.strip() for k in re.split(r"[,\n]+", os.environ.get("OPENAI_API_KEYS", "")) if k.strip()]
    if env_openai and not cfg_mgr.config["providers"]["openai_compatible"].get("api_keys"):
        cfg_mgr.config["providers"]["openai_compatible"]["api_keys"] = env_openai
        cfg_mgr.save_config()

    cfg_mgr.get_paths()


_init_environment()


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


def _sync_after_action(logs, upload_drive_exports=False):
    paths = cfg_mgr.get_paths()
    hf_client = HFDatasetSync(log_fn=lambda m: logs.append(str(m)))
    hf_client.push_data(paths["root"], BASE_DIR)
    if upload_drive_exports:
        drv = GDriveClient(log_fn=lambda m: logs.append(str(m)))
        if drv.enabled:
            drv.sync_exports_to_drive(paths["exports"], paths["backups"])


def ui_get_stats():
    _, db, _, _, _ = _get_runtime()
    st = db.get_stats()
    lenses = cfg_mgr.get_lenses()
    mode_lbl = "Google Drive API (دائم)" if gdrive_api.enabled else ("Colab Local Drive" if _is_colab_mounted() else "تخزين محلي / HF Dataset")
    lines = [
        f"حالة الربط: {mode_lbl} | HF Sync: {'مفعّل' if hf_sync.enabled else 'غير مفعّل'}",
        f"إجمالي الروايات المسجلة: {st['total']}",
        f"بانتظار الفرز (scanned): {st['by_status'].get('scanned', 0)}",
        f"مصنفة وجاهزة للتقطير (scouted): {st['by_status'].get('scouted', 0)}",
        f"قيد الاستئناف (chunking): {st['by_status'].get('chunking', 0)}",
        f"مكتملة (distilled): {st['by_status'].get('distilled', 0)}",
        f"أخطاء تحتاج مراجعة (error): {st['by_status'].get('error', 0)}",
        "--- توزيع العدسات ---",
    ]
    for lid, cnt in st["by_lens"].items():
        lname = lenses.get(lid, {}).get("display_name", lid)
        lines.append(f"• {lname}: {cnt}")
    return "\n".join(lines)


# -------------------- استيراد Google Drive (API دائم أو Colab) --------------------
def _extract_drive_folder_id(val):
    val = (val or "").strip()
    if not val:
        return ""
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", val)
    if m:
        return m.group(1)
    if " | [" in val and val.endswith("]"):
        return val.rsplit(" | [", 1)[1][:-1]
    return val


def ui_list_drive_folders(search_query):
    if gdrive_api.enabled:
        try:
            folders = gdrive_api.list_folders(query_name=(search_query or "").strip())
            choices = [f"{f['name']} | [{f['id']}]" for f in folders]
            return gr.Dropdown(choices=choices, value=choices[0] if choices else None), f"تم جلب {len(choices)} مجلد من Google Drive."
        except Exception as exc:
            return gr.Dropdown(choices=[]), f"خطأ في الاتصال بـ Google Drive: {exc}"

    # بديل محلي في حال التشغيل على Colab
    root = "/content/drive/MyDrive" if os.path.isdir("/content/drive/MyDrive") else cfg_mgr.config.get("project_root_dir", BASE_DIR)
    folders = [root]
    if os.path.isdir(root):
        for item in sorted(os.listdir(root)):
            p = os.path.join(root, item)
            if os.path.isdir(p) and not item.startswith("."):
                folders.append(p)
    return gr.Dropdown(choices=folders, value=folders[0]), "تم تحديث قائمة المجلدات المحلية."


def ui_list_drive_folder_files(selected_folder, custom_input):
    if gdrive_api.enabled:
        fid = _extract_drive_folder_id(custom_input) or _extract_drive_folder_id(selected_folder)
        if not fid:
            return gr.CheckboxGroup(choices=[], value=[]), "اختر مجلداً أو الصق رابط/معرّف المجلد أولاً."
        try:
            files = gdrive_api.list_novel_files(fid)
            choices = [f"{it['name']} | [{it['id']}]" for it in files]
            return gr.CheckboxGroup(choices=choices, value=[]), f"تم العثور على {len(choices)} رواية داخل المجلد."
        except Exception as exc:
            return gr.CheckboxGroup(choices=[], value=[]), f"تعذر قراءة الملفات: {exc}"

    target = (custom_input or "").strip() or (selected_folder or "").strip()
    if not target or not os.path.isdir(target):
        return gr.CheckboxGroup(choices=[], value=[]), f"المجلد غير موجود: {target}"
    files = scan_inbox_files([target])
    return gr.CheckboxGroup(choices=files, value=[]), f"تم العثور على {len(files)} رواية داخل المجلد."


def ui_select_all_drive_files(selected_folder, custom_input):
    chk, _ = ui_list_drive_folder_files(selected_folder, custom_input)
    choices = chk.choices if hasattr(chk, "choices") else []
    vals = [c[1] if isinstance(c, tuple) else c for c in choices]
    return gr.CheckboxGroup(choices=vals, value=vals)


def ui_clear_drive_selection():
    return []


def ui_import_from_drive(selected_items):
    if not selected_items:
        return "لم تحدد أي ملفات للاستيراد."
    paths, _, _, _, _ = _get_runtime()
    imported = 0

    if gdrive_api.enabled:
        for item in selected_items:
            if " | [" in item and item.endswith("]"):
                fname, id_part = item.rsplit(" | [", 1)
                fid = id_part[:-1]
                dest = safe_unique_dest(paths["inbox"], fname)
                gdrive_api.download_file(fid, dest)
                imported += 1
        return f"تم استيراد {imported} رواية من Google Drive إلى صندوق الوارد بنجاح!"

    for src in selected_items:
        if os.path.isfile(src):
            dest = safe_unique_dest(paths["inbox"], os.path.basename(src))
            shutil.copy2(src, dest)
            imported += 1
    return f"تم نسخ {imported} رواية إلى صندوق الوارد بنجاح!"


def ui_upload_to_inbox(files):
    if not files:
        return "لم يتم اختيار ملفات."
    paths, _, _, _, _ = _get_runtime()
    saved = []
    for f in files:
        src = f.name if hasattr(f, "name") else str(f)
        dest = safe_unique_dest(paths["inbox"], os.path.basename(src))
        shutil.copy2(src, dest)
        saved.append(os.path.basename(src))
    return f"تم رفع {len(saved)} ملف بنجاح إلى صندوق الوارد:\n" + "\n".join(saved)


# -------------------- أزرار التشغيل --------------------
def ui_scan_inbox():
    _, _, pipeline, _, logs = _get_runtime()
    pipeline.scan_inbox()
    _sync_after_action(logs, upload_drive_exports=False)
    return "\n".join(logs), ui_get_stats()


def ui_run_scout(limit):
    _, _, pipeline, _, logs = _get_runtime()
    pipeline.run_scout(max_items=int(limit or 0))
    _sync_after_action(logs, upload_drive_exports=False)
    return "\n".join(logs), ui_get_stats()


def ui_run_distill(limit, lens_choice):
    _, _, pipeline, _, logs = _get_runtime()
    lf = None if lens_choice == "الكل" else lens_choice
    pipeline.run_distillation(max_items=int(limit or 0), lens_filter=lf)
    _sync_after_action(logs, upload_drive_exports=False)
    return "\n".join(logs), ui_get_stats()


def ui_run_meta(lens_choice):
    _, _, pipeline, _, logs = _get_runtime()
    lf = None if lens_choice == "الكل" else lens_choice
    pipeline.run_meta_synthesis(lens_filter=lf)
    _sync_after_action(logs, upload_drive_exports=False)
    return "\n".join(logs), ui_get_stats()


def ui_run_export_and_cleanup(lens_choice):
    _, _, pipeline, exporter, logs = _get_runtime()
    lf = None if lens_choice == "الكل" else lens_choice
    exp_map = exporter.export_all_lenses(lens_filter=lf)
    pipeline.run_cleanup_gate(exp_map)
    if cfg_mgr.config.get("auto_backup_after_run", True):
        exporter.create_backup_snapshot()
    _sync_after_action(logs, upload_drive_exports=True)
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
    _sync_after_action(logs, upload_drive_exports=True)
    return "\n".join(logs), ui_get_stats()


def ui_sync_now():
    logs = []
    _sync_after_action(logs, upload_drive_exports=True)
    return "\n".join(logs) if logs else "اكتملت المزامنة."


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
            if kw in json.dumps(sec, ensure_ascii=False):
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
    return "\n\n".join(hits[:40]) if hits else f"لم يتم العثور على نتائج للكلمة: {kw}"


def ui_reset_error_novels():
    _, db, _, _, _ = _get_runtime()
    errs = db.list_novels(status="error")
    cnt = 0
    for r in errs:
        new_st = "scouted" if r.get("primary_lens") else "scanned"
        db.set_novel_status(r["id"], new_st, "")
        cnt += 1
    logs = []
    _sync_after_action(logs, upload_drive_exports=False)
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
    logs = []
    _sync_after_action(logs, upload_drive_exports=False)
    return "تم حفظ الإعدادات ومزامنتها مع السحابة بنجاح!"


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

    with gr.Blocks(title="Distillab Cloud — تطبيق التقطير والمختبر السردي") as demo:
        gr.HTML(RTL_STYLE_HTML)
        gr.Markdown("# Distillab Cloud\n### تطبيق التحليل المعماري وتقطير الروايات بالذكاء الاصطناعي (DOCX + MD)")

        with gr.Tab("1. لوحة التشغيل"):
            with gr.Row():
                limit_in = gr.Number(label="حد الروايات في هذه الجلسة (0 = الكل)", value=10, precision=0)
                lens_in = gr.Dropdown(label="العدسة المستهدفة", choices=lens_choices, value="الكل")

            btn_full = gr.Button("🚀 تشغيل دورة كاملة (مسح + فرز + تقطير + قسم 10 + تصدير + مزامنة)", variant="primary")

            with gr.Row():
                btn_scan = gr.Button("1️⃣ مسح الوارد")
                btn_scout = gr.Button("2️⃣ فرز ذكي")
                btn_distill = gr.Button("3️⃣ تقطير / استئناف")
                btn_meta = gr.Button("4️⃣ القسم 10")
                btn_export = gr.Button("5️⃣ تصدير + مزامنة")

            with gr.Row():
                log_box = gr.Textbox(label="سجل العمليات المباشر", lines=16, interactive=False)
                stats_box = gr.Textbox(label="حالة الربط والمكتبة", value=ui_get_stats, lines=16, interactive=False)

            btn_scan.click(ui_scan_inbox, outputs=[log_box, stats_box])
            btn_scout.click(ui_run_scout, inputs=[limit_in], outputs=[log_box, stats_box])
            btn_distill.click(ui_run_distill, inputs=[limit_in, lens_in], outputs=[log_box, stats_box])
            btn_meta.click(ui_run_meta, inputs=[lens_in], outputs=[log_box, stats_box])
            btn_export.click(ui_run_export_and_cleanup, inputs=[lens_in], outputs=[log_box, stats_box])
            btn_full.click(ui_run_full_cycle, inputs=[limit_in, lens_in], outputs=[log_box, stats_box])

        with gr.Tab("2. استيراد من Drive ورفع الملفات"):
            gr.Markdown("### الاستيراد المباشر من Google Drive (بدون نوافذ صلاحية)")
            with gr.Row():
                drv_search = gr.Textbox(label="بحث باسم مجلد في Drive (اختياري)", placeholder="اتركه فارغاً لعرض المجلدات")
                drv_custom = gr.Textbox(label="أو الصق رابط/معرّف المجلد مباشرة", placeholder="https://drive.google.com/drive/folders/...")
            with gr.Row():
                btn_drv_refresh = gr.Button("🔄 جلب مجلدات Drive")
                drv_folder_drop = gr.Dropdown(label="المجلدات", choices=[], allow_custom_value=True)
                btn_drv_list = gr.Button("📂 عرض الروايات بالداخل")

            drv_files_chk = gr.CheckboxGroup(label="الروايات المكتشفة (EPUB / PDF / DOCX / TXT)", choices=[])
            with gr.Row():
                btn_sel_all = gr.Button("✅ تحديد الكل")
                btn_sel_none = gr.Button("❎ إلغاء التحديد")
                btn_drv_import = gr.Button("📥 استيراد المحدد إلى قائمة التحليل", variant="primary")
            drv_status = gr.Textbox(label="حالة الاستيراد", lines=3)

            btn_drv_refresh.click(ui_list_drive_folders, inputs=[drv_search], outputs=[drv_folder_drop, drv_status])
            btn_drv_list.click(ui_list_drive_folder_files, inputs=[drv_folder_drop, drv_custom], outputs=[drv_files_chk, drv_status])
            btn_sel_all.click(ui_select_all_drive_files, inputs=[drv_folder_drop, drv_custom], outputs=[drv_files_chk])
            btn_sel_none.click(ui_clear_drive_selection, outputs=[drv_files_chk])
            btn_drv_import.click(ui_import_from_drive, inputs=[drv_files_chk], outputs=[drv_status])

            gr.Markdown("---\n### أو رفع ملفات مباشرة من الهاتف/الكمبيوتر")
            up_files = gr.File(label="اختر ملفات من جهازك", file_count="multiple")
            btn_up = gr.Button("⬆️ رفع إلى قائمة التحليل")
            up_status = gr.Textbox(label="حالة الرفع", lines=3)
            btn_up.click(ui_upload_to_inbox, inputs=[up_files], outputs=[up_status])

        with gr.Tab("3. المكتبة والبحث"):
            with gr.Row():
                btn_refresh_lib = gr.Button("🔄 تحديث الجدول")
                btn_retry_err = gr.Button("♻️ إعادة تفعيل المتعطلة (Error)")
            lib_table = gr.Dataframe(
                headers=["ID", "العنوان", "السلسلة", "مجلد", "العدسة", "الكلمات", "الحالة", "تنظيف", "ملاحظة"],
                value=ui_list_library,
                interactive=False
            )
            err_msg = gr.Textbox(label="الحالة", lines=1)
            btn_refresh_lib.click(ui_list_library, outputs=[lib_table])
            btn_retry_err.click(ui_reset_error_novels, outputs=[err_msg, lib_table])

            gr.Markdown("### بحث متقاطع في كل الروايات المحللة")
            with gr.Row():
                search_kw = gr.Textbox(label="كلمة البحث (بدون استهلاك API)", placeholder="مثال: السم، حجة غياب، ابتزاز...")
                btn_search = gr.Button("🔍 بحث")
            search_res = gr.Textbox(label="النتائج", lines=12)
            btn_search.click(ui_search_vault, inputs=[search_kw], outputs=[search_res])

        with gr.Tab("4. الإعدادات والمفاتيح"):
            init_vals = ui_load_settings()
            s_root = gr.Textbox(label="مسار البيانات المحلي داخل الخادم", value=init_vals[0])
            s_extra = gr.Textbox(label="مجلدات إضافية محلية (اختياري)", value=init_vals[1], lines=2)
            with gr.Row():
                s_prov = gr.Dropdown(label="المزود النشط", choices=list(cfg_mgr.config["providers"].keys()), value=init_vals[2])
                s_url = gr.Textbox(label="Base URL", value=init_vals[3])
            with gr.Row():
                s_m_scout = gr.Textbox(label="نموذج الفرز (Scout)", value=init_vals[4])
                s_m_dist = gr.Textbox(label="نموذج التقطير (Distill)", value=init_vals[5])
                s_m_meta = gr.Textbox(label="نموذج القسم 10 (Meta)", value=init_vals[6])
            s_keys = gr.Textbox(label="مفاتيح الـ API (مفتاح بكل سطر)", value=init_vals[7], lines=4, type="password")
            with gr.Row():
                s_delay = gr.Number(label="الفاصل الزمني (ثانية)", value=init_vals[8])
                s_cmode = gr.Dropdown(label="وضع السياق", choices=["smart_chunks", "full_novel"], value=init_vals[9])
                s_cwords = gr.Number(label="حد المقطع بالكلمات", value=init_vals[10], precision=0)
            with gr.Row():
                s_exp_w = gr.Number(label="حد التقسيم التلقائي للتصدير", value=init_vals[11], precision=0)
                s_meta_b = gr.Number(label="حجم حزمة القسم 10", value=init_vals[12], precision=0)
                s_mut = gr.Textbox(label="هدف التحوير 70% (اختياري)", value=init_vals[15])
            with gr.Row():
                s_clean = gr.Dropdown(
                    label="إجراء ما بعد الاكتمال",
                    choices=["archive_compressed", "move_to_trash", "permanent_delete", "keep"],
                    value=init_vals[13]
                )
                s_conf_del = gr.Checkbox(label="تأكيد الحذف النهائي", value=init_vals[14])

            btn_save_cfg = gr.Button("💾 حفظ الإعدادات", variant="primary")
            cfg_status = gr.Textbox(label="الحالة", lines=1)
            btn_save_cfg.click(
                ui_save_settings,
                inputs=[s_root, s_extra, s_prov, s_url, s_m_scout, s_m_dist, s_m_meta, s_keys, s_delay, s_cmode, s_cwords, s_exp_w, s_meta_b, s_clean, s_conf_del, s_mut],
                outputs=[cfg_status]
            )

        with gr.Tab("5. التحميل والمزامنة"):
            with gr.Row():
                btn_sync_now = gr.Button("☁️ مزامنة فورية مع HF Dataset و Google Drive", variant="primary")
                btn_ref_dl = gr.Button("🔄 تحديث قائمة الملفات الجاهزة")
            sync_msg = gr.Textbox(label="حالة المزامنة", lines=3)
            dl_drop = gr.Dropdown(label="اختر ملفاً لتنزيله (DOCX / MD / Backup ZIP)", choices=[])
            btn_dl = gr.Button("⬇️ تجهيز للتنزيل")
            dl_file = gr.File(label="الملف الجاهز")

            btn_sync_now.click(ui_sync_now, outputs=[sync_msg])
            btn_ref_dl.click(ui_list_downloadable_files, outputs=[dl_drop])
            btn_dl.click(ui_prepare_download, inputs=[dl_drop], outputs=[dl_file])

    return demo


if __name__ == "__main__":
    app = build_ui()
    app_user = (os.environ.get("APP_USERNAME") or "").strip()
    app_pass = (os.environ.get("APP_PASSWORD") or "").strip()

    launch_kwargs = {
        "server_name": "0.0.0.0",
        "server_port": int(os.environ.get("PORT", 7860)),
        "debug": False,
    }
    if app_user and app_pass:
        launch_kwargs["auth"] = (app_user, app_pass)
        launch_kwargs["auth_message"] = "أدخل بيانات الدخول الخاصة بك للوصول إلى مختبر Distillab"

    if _is_colab_mounted() or os.environ.get("GRADIO_SHARE", "0") == "1":
        launch_kwargs["share"] = True

    sig = inspect.signature(app.launch)
    if "pwa" in sig.parameters:
        launch_kwargs["pwa"] = True

    app.queue().launch(**launch_kwargs)