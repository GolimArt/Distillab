import hashlib
import json
import os
import re
from collections import defaultdict

from .ai_client import AIContentBlockedError, DailyQuotaExhaustedError, UniversalAIClient
from .prompts import (
    SYSTEM_ANALYST_PROMPT,
    build_chunk_digest_prompt,
    build_full_pass_a_prompt,
    build_full_pass_b_prompt,
    build_full_pass_c_prompt,
    build_meta_batch_prompt,
    build_meta_final_prompt,
    build_scout_prompt,
    build_synthesis_plot_prompt,
    build_synthesis_systems_chars_prompt,
)
from .readers import (
    build_scout_sample,
    compute_file_hash,
    compute_text_stats,
    execute_post_complete_cleanup,
    extract_clean_text,
    parse_filename_metadata,
    scan_inbox_files,
    split_text_into_chunks,
)


class NovelPipeline:
    def __init__(self, cfg_manager, db, log_fn=print):
        self.cfg_mgr = cfg_manager
        self.db = db
        self.log = log_fn

    def _get_client_and_models(self):
        pname, pcfg = self.cfg_mgr.get_active_provider_cfg()
        client = UniversalAIClient(pname, pcfg, log_fn=self.log)
        return client, pcfg

    def _safe_cache_path(self, paths, file_hash):
        return os.path.join(paths["cache"], f"{file_hash}.txt")

    def _load_novel_text(self, novel):
        cpath = novel.get("cached_text_path", "")
        if cpath and os.path.exists(cpath):
            with open(cpath, "r", encoding="utf-8") as f:
                return f.read()
        orig = novel.get("original_path", "")
        if orig and os.path.exists(orig):
            text = extract_clean_text(orig)
            if cpath:
                os.makedirs(os.path.dirname(cpath), exist_ok=True)
                with open(cpath, "w", encoding="utf-8") as f:
                    f.write(text)
            return text
        raise FileNotFoundError(f"تعذر العثور على نص الرواية: {novel.get('file_name')}")

    # ------------------------------------------------------------------
    # المرحلة 1: مسح صندوق الوارد وحفظ النصوص النظيفة والإحصائيات
    # ------------------------------------------------------------------
    def scan_inbox(self):
        paths = self.cfg_mgr.get_paths()
        inbox_dirs = [paths["inbox"]] + paths["extra_inboxes"]
        files = scan_inbox_files(inbox_dirs)

        added = 0
        skipped = 0
        failed = 0
        self.log(f"[المسح] تم العثور على {len(files)} ملف في مجلدات الوارد...")

        for fpath in files:
            fname = os.path.basename(fpath)
            try:
                fhash = compute_file_hash(fpath)
                existing = self.db.get_novel_by_hash(fhash)
                if existing:
                    skipped += 1
                    continue

                text = extract_clean_text(fpath)
                if not text or len(text.split()) < 100:
                    self.log(f"[تجاهل] الملف '{fname}' فارغ أو قصير جداً.")
                    failed += 1
                    continue

                cache_path = self._safe_cache_path(paths, fhash)
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(text)

                wc, cc, chc = compute_text_stats(text)
                title, series, vol_num = parse_filename_metadata(fpath)
                self.db.upsert_scanned_novel({
                    "file_hash": fhash,
                    "file_name": fname,
                    "original_path": fpath,
                    "cached_text_path": cache_path,
                    "file_format": os.path.splitext(fname)[1].lower(),
                    "word_count": wc,
                    "char_count": cc,
                    "chapter_count": chc,
                    "title": title,
                    "series_name": series,
                    "volume_number": vol_num,
                })
                added += 1
                self.log(f"  + أُضيف: {fname} ({wc:,} كلمة | ~{chc} فصل)")
            except Exception as exc:
                failed += 1
                self.log(f"  ! خطأ في قراءة '{fname}': {exc}")

        self.log(f"[انتهى المسح] جديد: {added} | موجود مسبقاً: {skipped} | تعذر: {failed}")
        return {"added": added, "skipped": skipped, "failed": failed}

    # ------------------------------------------------------------------
    # المرحلة 2: الفرز الذكي بالذكاء الاصطناعي (Scout Pass)
    # ------------------------------------------------------------------
    def run_scout(self, max_items=0):
        client, pcfg = self._get_client_and_models()
        model = pcfg["scout_model"]
        lenses = self.cfg_mgr.get_lenses()
        pending = self.db.list_novels(status="scanned")
        if max_items and max_items > 0:
            pending = pending[:max_items]

        self.log(f"[الفرز الذكي] روايات بانتظار التصنيف: {len(pending)}")
        done_count = 0

        for novel in pending:
            try:
                text = self._load_novel_text(novel)
                sample = build_scout_sample(text, 4500)
                prompt = build_scout_prompt(novel["file_name"], novel, sample, lenses)
                res = client.generate_json(model, SYSTEM_ANALYST_PROMPT, prompt)

                lens_id = res.get("primary_lens", "general_lit")
                if lens_id not in lenses:
                    lens_id = "general_lit"
                res["primary_lens"] = lens_id

                # الاحتفاظ باسم السلسلة المستخرج من اسم الملف إذا لم يحدده النموذج
                if not res.get("series_name") and novel.get("series_name"):
                    res["series_name"] = novel["series_name"]
                if not res.get("volume_number") and novel.get("volume_number"):
                    res["volume_number"] = novel["volume_number"]
                if not res.get("title"):
                    res["title"] = novel["title"]

                self.db.update_scout_info(novel["id"], res)
                done_count += 1
                self.log(f"  ✓ صُنّف [{res['title']}] --> {lenses[lens_id]['display_name']}")
            except DailyQuotaExhaustedError:
                self.log("[توقف آمن] نفدت الحصة اليومية أثناء الفرز. تم حفظ كل ما سبق.")
                break
            except AIContentBlockedError as exc:
                self.db.set_novel_status(novel["id"], "error", f"محتوى محجوب: {exc}")
                self.log(f"  ! حُجب المحتوى في {novel['file_name']}: {exc}")
            except Exception as exc:
                self.db.set_novel_status(novel["id"], "error", str(exc)[:500])
                self.log(f"  ! خطأ في تصنيف {novel['file_name']}: {exc}")

        return done_count

    # ------------------------------------------------------------------
    # المرحلة 3: التقطير العميق (وضع كامل أو تقطيع ذكي مع استئناف)
    # ------------------------------------------------------------------
    def _merge_chunk_digests(self, digests):
        philosophy = []
        seen_quotes = set()
        dialogues = []
        sensory_map = defaultdict(list)
        digest_texts = []

        for idx, d in enumerate(digests):
            digest_texts.append(
                f"=== خلاصة المقطع {idx + 1} ===\n"
                f"الأحداث: {d.get('plot_events_digest', '')}\n"
                f"الخيوط: {json.dumps(d.get('threads_seen', []), ensure_ascii=False)}\n"
                f"البذور والكشوفات: {json.dumps(d.get('seeds_and_reveals', []), ensure_ascii=False)}\n"
                f"الأنظمة والقيود: {json.dumps(d.get('system_rules_notes', []), ensure_ascii=False)}\n"
                f"التكتيكات: {json.dumps(d.get('tactics_notes', []), ensure_ascii=False)}\n"
                f"الشخصيات: {json.dumps(d.get('character_notes', []), ensure_ascii=False)}"
            )
            for q in d.get("philosophy_quotes", []):
                norm = re.sub(r"\s+", " ", (q.get("quote") or "").strip())
                if norm and norm not in seen_quotes:
                    seen_quotes.add(norm)
                    philosophy.append(q)
            dialogues.extend(d.get("dialogues", []))
            for s in d.get("sensory_items", []):
                cat = s.get("category", "تعبيرات عامة")
                sensory_map[cat].append({
                    "title": s.get("title", ""),
                    "quote": s.get("quote", ""),
                    "stylistic_rule": s.get("stylistic_rule", "")
                })

        sensory_list = [{"category": k, "items": v} for k, v in sensory_map.items()]
        return philosophy, dialogues, sensory_list, "\n\n".join(digest_texts)

    def _distill_single_novel(self, novel, client, model):
        cfg = self.cfg_mgr.config
        lenses = self.cfg_mgr.get_lenses()
        lens_id = novel.get("primary_lens") or "general_lit"
        if lens_id not in lenses:
            lens_id = "general_lit"
        lens_cfg = lenses[lens_id]

        mutation_target = (cfg.get("custom_mutation_target") or "").strip() or lens_cfg["mutation_target_default"]
        title = novel.get("title") or novel["file_name"]
        text = self._load_novel_text(novel)

        use_full = (
            cfg.get("chunk_mode", "smart_chunks") == "full_novel"
            and novel["word_count"] <= int(cfg.get("full_novel_max_words", 130000))
        )

        if use_full:
            self.log(f"  -> تحليل رواية كاملة في السياق: {title} ({novel['word_count']:,} كلمة)")
            res_a = client.generate_json(model, SYSTEM_ANALYST_PROMPT, build_full_pass_a_prompt(title, lens_cfg, text))
            res_b = client.generate_json(model, SYSTEM_ANALYST_PROMPT, build_full_pass_b_prompt(title, lens_cfg, mutation_target, text))
            res_c = client.generate_json(model, SYSTEM_ANALYST_PROMPT, build_full_pass_c_prompt(title, lens_cfg, mutation_target, text))

            sections = {
                "section_1_philosophy": res_a.get("section_1_philosophy", []),
                "section_2_dialogues": res_a.get("section_2_dialogues", []),
                "section_3_arc_structure": res_b.get("section_3_arc_structure", {}),
                "section_4_foreshadowing": res_b.get("section_4_foreshadowing", []),
                "section_5_blueprint": res_b.get("section_5_blueprint", {}),
                "section_6_system_laws": res_c.get("section_6_system_laws", {}),
                "section_7_micro_tactics": res_c.get("section_7_micro_tactics", []),
                "section_8_sensory_lexicon": res_a.get("section_8_sensory_lexicon", []),
                "section_9_characters": res_c.get("section_9_characters", {}),
            }
            self.db.save_analysis(novel["id"], lens_id, model, sections)
            return

        # وضع التقطيع الذكي (الآمن للباقة المجانية والروايات الضخمة مع استئناف تلقائي)
        chunk_max = int(cfg.get("chunk_max_words", 45000))
        text_chunks = split_text_into_chunks(text, chunk_max)
        existing_chunks = self.db.get_chunks(novel["id"])

        if len(existing_chunks) != len(text_chunks):
            self.db.clear_chunks(novel["id"])
            self.db.register_chunks(novel["id"], [len(c.split()) for c in text_chunks])
            existing_chunks = self.db.get_chunks(novel["id"])

        self.db.set_novel_status(novel["id"], "chunking")
        total_chunks = len(text_chunks)
        self.log(f"  -> تحليل متدرج ({total_chunks} مقطع): {title}")

        for ch_row in existing_chunks:
            idx = ch_row["chunk_index"]
            if ch_row["status"] == "done" and ch_row["digest_json"]:
                continue
            self.log(f"     • معالجة المقطع {idx + 1}/{total_chunks} ...")
            prompt = build_chunk_digest_prompt(title, lens_cfg, idx, total_chunks, text_chunks[idx])
            digest = client.generate_json(model, SYSTEM_ANALYST_PROMPT, prompt)
            self.db.save_chunk_digest(novel["id"], idx, digest)

        # كل المقاطع اكتملت: ندمج ونولّف الأقسام المعمارية والشخصيات
        completed_chunks = self.db.get_chunks(novel["id"])
        digests = [json.loads(r["digest_json"]) for r in completed_chunks]
        philosophy, dialogues, sensory_list, combined_digests_text = self._merge_chunk_digests(digests)

        self.log(f"     • توليف البنية المعمارية والأدلة والشخصيات لـ {title} ...")
        res_plot = client.generate_json(
            model, SYSTEM_ANALYST_PROMPT,
            build_synthesis_plot_prompt(title, lens_cfg, mutation_target, combined_digests_text)
        )
        res_sys = client.generate_json(
            model, SYSTEM_ANALYST_PROMPT,
            build_synthesis_systems_chars_prompt(title, lens_cfg, mutation_target, combined_digests_text)
        )

        sections = {
            "section_1_philosophy": philosophy,
            "section_2_dialogues": dialogues,
            "section_3_arc_structure": res_plot.get("section_3_arc_structure", {}),
            "section_4_foreshadowing": res_plot.get("section_4_foreshadowing", []),
            "section_5_blueprint": res_plot.get("section_5_blueprint", {}),
            "section_6_system_laws": res_sys.get("section_6_system_laws", {}),
            "section_7_micro_tactics": res_sys.get("section_7_micro_tactics", []),
            "section_8_sensory_lexicon": sensory_list,
            "section_9_characters": res_sys.get("section_9_characters", {}),
        }
        self.db.save_analysis(novel["id"], lens_id, model, sections)

    def run_distillation(self, max_items=0, lens_filter=None):
        client, pcfg = self._get_client_and_models()
        model = pcfg["distill_model"]

        # نستأنف أولاً أي رواية توقفت في المنتصف (chunking)، ثم المصنفة (scouted)
        targets = self.db.list_novels(status="chunking", lens_id=lens_filter)
        targets.extend(self.db.list_novels(status="scouted", lens_id=lens_filter))

        if max_items and max_items > 0:
            targets = targets[:max_items]

        self.log(f"[التقطير] روايات في قائمة الانتظار: {len(targets)}")
        completed = 0

        for novel in targets:
            try:
                self._distill_single_novel(novel, client, model)
                completed += 1
                self.log(f"  ✓ اكتمل تقطير: {novel.get('title') or novel['file_name']}")
            except DailyQuotaExhaustedError:
                self.log("[توقف آمن] نفدت الحصة اليومية. التقدم محفوظ بالكامل، استأنف في الجلسة التالية.")
                break
            except AIContentBlockedError as exc:
                self.db.set_novel_status(novel["id"], "error", f"محتوى محجوب: {exc}")
                self.log(f"  ! حُجب المحتوى في {novel['file_name']}: {exc}")
            except Exception as exc:
                self.db.set_novel_status(novel["id"], "error", str(exc)[:500])
                self.log(f"  ! خطأ في تقطير {novel['file_name']}: {exc}")

        return completed

    # ------------------------------------------------------------------
    # المرحلة 4: القسم العاشر — التوليف الهرمي (Map-Reduce) لكل عدسة
    # ------------------------------------------------------------------
    def _compact_novel_summary_for_meta(self, novel_row):
        sec = novel_row["sections"]
        return {
            "title": novel_row.get("title") or novel_row["file_name"],
            "sub_tags": novel_row.get("sub_tags", []),
            "arc": sec.get("section_3_arc_structure", {}),
            "blueprint_flow": sec.get("section_5_blueprint", {}).get("summary_flow", ""),
            "foreshadowing_titles": [f.get("title", "") for f in sec.get("section_4_foreshadowing", [])],
            "system_laws": sec.get("section_6_system_laws", {}),
            "tactics": [
                {"name": t.get("name", ""), "equation": t.get("abstract_equation", "")}
                for t in sec.get("section_7_micro_tactics", [])
            ],
            "characters": [
                {"name": c.get("name_and_title", ""), "contradiction": c.get("inner_contradiction", "")}
                for c in sec.get("section_9_characters", {}).get("characters", [])
            ],
            "top_themes": [q.get("theme", "") + ": " + q.get("psychological_rule", "") for q in sec.get("section_1_philosophy", [])[:8]],
        }

    def run_meta_synthesis(self, lens_filter=None):
        client, pcfg = self._get_client_and_models()
        model = pcfg.get("meta_model") or pcfg["distill_model"]
        batch_size = max(2, int(self.cfg_mgr.config.get("meta_batch_size", 8)))
        lenses = self.cfg_mgr.get_lenses()

        target_lenses = [lens_filter] if lens_filter else list(lenses.keys())
        for lid in target_lenses:
            if lid not in lenses:
                continue
            novels = self.db.get_distilled_novels_with_analyses(lid)
            if not novels:
                continue

            lens_cfg = lenses[lid]
            self.log(f"[القسم 10 - التوليف الهرمي] عدسة {lens_cfg['display_name']} ({len(novels)} رواية)...")

            # المستوى الأول (Map): كل 8-10 روايات في حزمة
            batches = [novels[i:i + batch_size] for i in range(0, len(novels), batch_size)]
            batch_signatures = []

            try:
                for b_idx, b_novels in enumerate(batches):
                    sig_src = "|".join(f"{n['id']}:{n['analysis_updated_at']}" for n in b_novels)
                    sig = hashlib.sha256(sig_src.encode("utf-8")).hexdigest()
                    batch_signatures.append(sig)

                    existing_b = self.db.get_meta_batch(lid, b_idx)
                    if existing_b and existing_b["novel_hashes_sig"] == sig:
                        continue

                    self.log(f"  • المستوى الأول: توليف الحزمة {b_idx + 1}/{len(batches)} ({len(b_novels)} روايات)...")
                    compact_list = [self._compact_novel_summary_for_meta(n) for n in b_novels]
                    prompt = build_meta_batch_prompt(lens_cfg, b_idx, compact_list)
                    syn = client.generate_json(model, SYSTEM_ANALYST_PROMPT, prompt)
                    self.db.save_meta_batch(lid, b_idx, [n["id"] for n in b_novels], sig, syn, model)

                self.db.delete_stale_meta_batches(lid, len(batches) - 1)

                # المستوى الثاني (Reduce): الدمج الشامل للعدسة
                all_batch_rows = self.db.get_all_meta_batches(lid)
                final_sig = hashlib.sha256("|".join(batch_signatures).encode("utf-8")).hexdigest()
                existing_final = self.db.get_meta_final(lid)

                if existing_final and existing_final["batches_sig"] == final_sig:
                    self.log(f"  ✓ الخلاصة التوليفية الشاملة لـ {lens_cfg['display_name']} محدثة مسبقاً.")
                    continue

                self.log(f"  • المستوى الثاني: توليد الخلاصة التوليفية الشاملة ({len(all_batch_rows)} حزم)...")
                batch_jsons = [json.loads(r["synthesis_json"]) for r in all_batch_rows]
                final_prompt = build_meta_final_prompt(lens_cfg, len(novels), batch_jsons)
                final_syn = client.generate_json(model, SYSTEM_ANALYST_PROMPT, final_prompt)
                self.db.save_meta_final(lid, final_sig, final_syn, model)
                self.log(f"  ✓ اكتمل القسم 10 لـ {lens_cfg['display_name']}.")

            except DailyQuotaExhaustedError:
                self.log("[توقف آمن] نفدت الحصة اليومية أثناء التوليف الهرمي. الحزم المنجزة محفوظة.")
                break
            except Exception as exc:
                self.log(f"  ! خطأ في التوليف الهرمي للعدسة {lid}: {exc}")

    # ------------------------------------------------------------------
    # المرحلة 5: بوابة التحقق والنظافة الآمنة بعد التصدير
    # ------------------------------------------------------------------
    def _is_novel_analysis_valid(self, novel_id, lens_id):
        novels = self.db.get_distilled_novels_with_analyses(lens_id)
        for n in novels:
            if n["id"] == novel_id:
                sec = n.get("sections", {})
                has_core = bool(sec.get("section_1_philosophy") or sec.get("section_3_arc_structure") or sec.get("section_9_characters"))
                return has_core
        return False

    def run_cleanup_gate(self, exported_lens_files):
        cfg = self.cfg_mgr.config
        action = cfg.get("post_complete_action", "archive_compressed")
        confirm_del = bool(cfg.get("confirm_permanent_delete", False))
        paths = self.cfg_mgr.get_paths()

        distilled = self.db.list_novels(status="distilled")
        cleaned = 0

        for novel in distilled:
            if novel.get("cleanup_done"):
                continue

            lid = novel.get("primary_lens")
            # شرط 1: التأكد من وجود ملفات التصدير الفعلية لهذه العدسة على Drive
            exp_files = exported_lens_files.get(lid, [])
            if not exp_files or not all(os.path.exists(p) and os.path.getsize(p) > 0 for p in exp_files):
                continue

            # شرط 2: التأكد من أن التحليل غير فارغ
            if not self._is_novel_analysis_valid(novel["id"], lid):
                continue

            # شرط 3: إذا كانت جزءاً من سلسلة، لا ننظف أي ملف حتى تكتمل كل أجزاء السلسلة
            sname = (novel.get("series_name") or "").strip()
            if sname:
                series_rows = self.db.get_series_novels(sname)
                if any(r["status"] != "distilled" for r in series_rows):
                    continue

            try:
                arc_path = execute_post_complete_cleanup(novel, paths, action, confirm_permanent_delete=confirm_del)
                self.db.mark_cleanup_done(novel["id"], arc_path)
                cleaned += 1
                self.log(f"  ✓ [بوابة الأمان: {action}] {novel['file_name']}")
            except Exception as exc:
                self.log(f"  ! تعذر تنظيف {novel['file_name']}: {exc}")

        return cleaned