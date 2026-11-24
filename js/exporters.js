// مُصدّر ملفات Markdown و DOCX (RTL عربي حقيقي) + التقسيم التلقائي + القسم 10 + النسخ الاحتياطي ZIP
import {
  AlignmentType,
  Document,
  HeadingLevel,
  Packer,
  PageBreak,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} from "https://esm.sh/docx@8.5.0";
import JSZip from "https://esm.sh/jszip@3.10.1";

function safeFilename(name) {
  return String(name || "export").replace(/[\\/*?:"<>|]+/g, "_").trim();
}

export function countNovelAnalysisWords(novel) {
  const raw = JSON.stringify(novel.sections || {});
  const matches = raw.match(/[\w\u0600-\u06FF]+/g);
  return matches ? matches.length : 0;
}

export function splitNovelsIntoParts(novels, maxWordsPerPart = 350000) {
  if (!novels || !novels.length) return [];
  const parts = [];
  let current = [];
  let currentWords = 0;

  for (const n of novels) {
    const wc = countNovelAnalysisWords(n);
    // قاعدة حازمة: لا يُقص أي عمل/رواية من منتصفها أبداً
    if (current.length > 0 && currentWords + wc > maxWordsPerPart) {
      parts.push(current);
      current = [];
      currentWords = 0;
    }
    current.push(n);
    currentWords += wc;
  }
  if (current.length > 0) parts.push(current);
  return parts;
}

function getSectionTitle(secId, defaultTitle, lensCfg) {
  if (secId === "system_laws") return lensCfg.section_6_title || defaultTitle;
  if (secId === "micro_tactics") return lensCfg.section_7_title || defaultTitle;
  return defaultTitle;
}

// ------------------------------------------------------------------
// توليد Markdown منظم لـ Google AI Studio
// ------------------------------------------------------------------
export function buildPartMarkdown(lensCfg, partIdx, totalParts, partNovels, sectionsOrder) {
  const lines = [];
  const pStr = String(partIdx).padStart(2, "0");
  const tStr = String(totalParts).padStart(2, "0");
  lines.push(`# ${lensCfg.display_name} — الجزء ${pStr} من ${tStr}`);
  lines.push(`> مرجع منظم لـ AI Studio | عدد الروايات في هذا الجزء: ${partNovels.length}\n`);

  lines.push("## فهرس روايات هذا الجزء");
  lines.push("| # | عنوان الرواية | المؤلف | السلسلة / المجلد | الوسوم | كلمات التحليل |");
  lines.push("|---|---|---|---|---|---|");
  partNovels.forEach((n, idx) => {
    const title = n.title || n.file_name;
    const author = n.author || "غير معروف";
    const series = n.series_name ? `${n.series_name} (م${n.volume_number || 0})` : "مستقلة";
    const tags = (n.sub_tags || []).join("، ");
    const wc = countNovelAnalysisWords(n);
    lines.push(`| ${idx + 1} | ${title} | ${author} | ${series} | ${tags} | ${wc.toLocaleString()} |`);
  });
  lines.push("\n---\n");

  for (const sm of sectionsOrder) {
    const sid = sm.id;
    const stitle = getSectionTitle(sid, sm.title, lensCfg);
    lines.push(`## القسم ${sm.num}: ${stitle}\n`);

    for (const n of partNovels) {
      const ntitle = n.title || n.file_name;
      const sec = n.sections || {};

      if (sid === "philosophy_bank") {
        const items = sec.section_1_philosophy || [];
        if (items.length) {
          lines.push(`### [الرواية: ${ntitle}]`);
          items.forEach((it, i) => {
            lines.push(`${i + 1}. **"${it.quote || ""}"** (${it.chapter_context || ""})`);
            lines.push(`   - **المحور:** ${it.theme || ""}`);
            lines.push(`   - **القاعدة النفسية:** ${it.psychological_rule || ""}`);
            lines.push(`   - **الوظيفة السردية:** ${it.narrative_function || ""}`);
          });
          lines.push("");
        }
      } else if (sid === "dialogue_engineering") {
        const items = sec.section_2_dialogues || [];
        if (items.length) {
          lines.push(`### [الرواية: ${ntitle}]`);
          for (const it of items) {
            lines.push(`#### ${it.title || "موقف حواري"} (${it.chapter_context || ""})`);
            lines.push(`- **السطح المنطوق:** ${it.spoken_surface || ""}`);
            lines.push(`- **العمق الباطني:** ${it.hidden_subtext || ""}`);
            lines.push(`- **التكتيك (${it.tactic_name || ""}):** ${it.tactical_breakdown || ""}\n`);
          }
        }
      } else if (sid === "arc_structure") {
        const arc = sec.section_3_arc_structure || {};
        if (arc.opening_hook || (arc.parallel_threads || []).length) {
          lines.push(`### [الرواية: ${ntitle}]`);
          lines.push(`- **الافتتاحية:** ${arc.opening_hook || ""}`);
          for (const th of arc.parallel_threads || []) {
            lines.push(`  - **خيط (${th.name || ""}):** ${th.progression || ""}`);
          }
          lines.push(`- **ذروة التصادم:** ${arc.climax_collision || ""}`);
          if (arc.open_threads) lines.push(`- **الخيوط المفتوحة:** ${arc.open_threads}`);
          lines.push("");
        }
      } else if (sid === "foreshadowing") {
        const items = sec.section_4_foreshadowing || [];
        if (items.length) {
          lines.push(`### [الرواية: ${ntitle}]`);
          items.forEach((it, i) => {
            lines.push(`${i + 1}. **${it.title || ""}**`);
            lines.push(`   - **البذرة المبكرة:** ${it.early_seed || ""}`);
            lines.push(`   - **التمويه:** ${it.camouflage_method || ""}`);
            lines.push(`   - **التفجير/الحصاد:** ${it.payoff_twist || ""}`);
          });
          lines.push("");
        }
      } else if (sid === "abstract_blueprints") {
        const bp = sec.section_5_blueprint || {};
        if (bp.summary_flow || (bp.stages || []).length) {
          lines.push(`### [الرواية: ${ntitle}]`);
          lines.push(`- **المسار القياسي:** \`${bp.summary_flow || ""}\``);
          for (const st of bp.stages || []) {
            lines.push(`  - **مرحلة ${st.stage_num || ""}: ${st.stage_name || ""}** — ${st.engineering || ""} | *التوجيه والكسر:* ${st.expectation_vs_twist || ""}`);
          }
          if (bp.mutation_70_example) lines.push(`- **تحوير 70%:** ${bp.mutation_70_example}`);
          lines.push("");
        }
      } else if (sid === "system_laws") {
        const sl = sec.section_6_system_laws || {};
        if (Object.keys(sl).length) {
          lines.push(`### [الرواية: ${ntitle}]`);
          const mapLabels = [
            ["mechanics", "آليات العمل"],
            ["costs_and_side_effects", "التكلفة والآثار الجانبية"],
            ["weaknesses_and_balance", "نقاط الضعف والتوازن"],
            ["resource_economy", "اقتصاد الموارد والندرة"],
          ];
          for (const [k, lbl] of mapLabels) {
            const vals = sl[k] || [];
            if (vals.length) {
              lines.push(`- **${lbl}:**`);
              for (const v of vals) lines.push(`  - ${v}`);
            }
          }
          const muts = sl.mutations_70 || [];
          if (muts.length) {
            lines.push("- **تحوير الآليات 70%:**");
            for (const m of muts) {
              lines.push(`  - **${m.mutated_name || ""}** (عن: ${m.original_name || ""}): ${m.new_mechanism || ""} | *القيد القاتل:* ${m.fatal_cost || ""}`);
            }
          }
          lines.push("");
        }
      } else if (sid === "micro_tactics") {
        const items = sec.section_7_micro_tactics || [];
        if (items.length) {
          lines.push(`### [الرواية: ${ntitle}]`);
          for (const it of items) {
            lines.push(`#### ${it.name || ""}`);
            lines.push(`- **الموقف المرجعي:** ${it.reference_scene || ""}`);
            lines.push(`- **المعادلة المجردة:** \`${it.abstract_equation || ""}\``);
            lines.push(`- **التنفيذ:** ${it.execution_steps || ""}`);
            lines.push(`- **شرط النجاح:** ${it.success_condition || ""} | **ثغرة الفشل:** ${it.failure_risk || ""}\n`);
          }
        }
      } else if (sid === "sensory_lexicon") {
        const cats = sec.section_8_sensory_lexicon || [];
        if (cats.length) {
          lines.push(`### [الرواية: ${ntitle}]`);
          for (const cat of cats) {
            lines.push(`#### ${cat.category || ""}`);
            for (const it of cat.items || []) {
              lines.push(`- **${it.title || ""}:** "${it.quote || ""}" — *القاعدة:* ${it.stylistic_rule || ""}`);
            }
          }
          lines.push("");
        }
      } else if (sid === "character_dna") {
        const ch = sec.section_9_characters || {};
        const chars = ch.characters || [];
        const muts = ch.mutations_70 || [];
        if (chars.length || muts.length) {
          lines.push(`### [الرواية: ${ntitle}]`);
          for (const c of chars) {
            lines.push(`#### ${c.name_and_title || ""}`);
            lines.push(`- **دلالة الاسم:** ${c.name_symbolism || ""}`);
            lines.push(`- **القناع الخارجي:** ${c.outer_mask || ""}`);
            lines.push(`- **الدافع الخفي:** ${c.hidden_motive || ""}`);
            lines.push(`- **التناقض الداخلي:** ${c.inner_contradiction || ""}`);
            lines.push(`- **اللازمة المميزة:** ${c.signature_habit || ""}`);
            lines.push(`- **الخصائص ومسار التحول:** ${c.physical_and_psych_arc || ""}\n`);
          }
          if (muts.length) {
            lines.push("#### شخصيات مولدة بتحوير 70%");
            for (const m of muts) {
              lines.push(`- **${m.new_name_and_title || ""}** (عن: ${m.inspired_by || ""} | ${m.target_world || ""}): القناع: ${m.outer_mask || ""} | الدافع: ${m.hidden_motive || ""} | اللازمة: ${m.signature_habit || ""} | الخصائص: ${m.traits || ""}`);
            }
          }
          lines.push("");
        }
      }
    }
  }

  return lines.join("\n");
}

// ------------------------------------------------------------------
// دوال مساعدة لإنشاء ملف DOCX عربي منسق (RTL)
// ------------------------------------------------------------------
function rtlHeading(text, level = HeadingLevel.HEADING_1) {
  return new Paragraph({
    heading: level,
    bidirectional: true,
    alignment: AlignmentType.RIGHT,
    children: [new TextRun({ text: String(text || ""), bold: true, rightToLeft: true, font: "Arial" })],
  });
}

function rtlPara(label = "", value = "", bullet = false) {
  const children = [];
  if (label) {
    children.push(new TextRun({ text: `${label}: `, bold: true, rightToLeft: true, font: "Arial", size: 22 }));
  }
  if (value) {
    children.push(new TextRun({ text: String(value), bold: false, rightToLeft: true, font: "Arial", size: 22 }));
  }
  const opts = {
    bidirectional: true,
    alignment: AlignmentType.RIGHT,
    children,
  };
  if (bullet) opts.bullet = { level: 0 };
  return new Paragraph(opts);
}

function rtlTable(headers, rows) {
  const headerRow = new TableRow({
    children: headers.map(
      (h) =>
        new TableCell({
          children: [
            new Paragraph({
              bidirectional: true,
              alignment: AlignmentType.RIGHT,
              children: [new TextRun({ text: h, bold: true, rightToLeft: true, font: "Arial", size: 20 })],
            }),
          ],
        })
    ),
  });

  const dataRows = rows.map(
    (r) =>
      new TableRow({
        children: r.map(
          (val) =>
            new TableCell({
              children: [
                new Paragraph({
                  bidirectional: true,
                  alignment: AlignmentType.RIGHT,
                  children: [new TextRun({ text: String(val ?? ""), rightToLeft: true, font: "Arial", size: 20 })],
                }),
              ],
            })
        ),
      })
  );

  return new Table({
    visuallyRightToLeft: true,
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: [headerRow, ...dataRows],
  });
}

export async function buildPartDocxBlob(lensCfg, partIdx, totalParts, partNovels, sectionsOrder) {
  const pStr = String(partIdx).padStart(2, "0");
  const tStr = String(totalParts).padStart(2, "0");
  const children = [
    rtlHeading(`${lensCfg.display_name} — الجزء ${pStr} من ${tStr}`, HeadingLevel.HEADING_1),
    rtlPara("عدد الروايات في هذا الجزء", String(partNovels.length)),
    rtlHeading("فهرس روايات هذا الجزء", HeadingLevel.HEADING_2),
  ];

  const rows = partNovels.map((n, idx) => [
    String(idx + 1),
    n.title || n.file_name,
    n.author || "غير معروف",
    n.series_name ? `${n.series_name} (م${n.volume_number || 0})` : "مستقلة",
    (n.sub_tags || []).join("، "),
    countNovelAnalysisWords(n).toLocaleString(),
  ]);
  children.push(rtlTable(["#", "عنوان الرواية", "المؤلف", "السلسلة / المجلد", "الوسوم", "كلمات التحليل"], rows));

  for (const sm of sectionsOrder) {
    const sid = sm.id;
    const stitle = getSectionTitle(sid, sm.title, lensCfg);
    children.push(new Paragraph({ children: [new PageBreak()] }));
    children.push(rtlHeading(`القسم ${sm.num}: ${stitle}`, HeadingLevel.HEADING_1));

    for (const n of partNovels) {
      const ntitle = n.title || n.file_name;
      const sec = n.sections || {};

      if (sid === "philosophy_bank") {
        const items = sec.section_1_philosophy || [];
        if (items.length) {
          children.push(rtlHeading(`من رواية: ${ntitle}`, HeadingLevel.HEADING_2));
          items.forEach((it, i) => {
            children.push(rtlPara(`${i + 1}) الاقتباس (${it.chapter_context || ""})`, `"${it.quote || ""}"`));
            children.push(rtlPara("المحور", it.theme || "", true));
            children.push(rtlPara("القاعدة النفسية", it.psychological_rule || "", true));
            children.push(rtlPara("الوظيفة السردية", it.narrative_function || "", true));
          });
        }
      } else if (sid === "dialogue_engineering") {
        const items = sec.section_2_dialogues || [];
        if (items.length) {
          children.push(rtlHeading(`من رواية: ${ntitle}`, HeadingLevel.HEADING_2));
          for (const it of items) {
            children.push(rtlHeading(`${it.title || "موقف حواري"} (${it.chapter_context || ""})`, HeadingLevel.HEADING_3));
            children.push(rtlPara("السطح المنطوق", it.spoken_surface || "", true));
            children.push(rtlPara("العمق الباطني", it.hidden_subtext || "", true));
            children.push(rtlPara(`التكتيك (${it.tactic_name || ""})`, it.tactical_breakdown || "", true));
          }
        }
      } else if (sid === "arc_structure") {
        const arc = sec.section_3_arc_structure || {};
        if (arc.opening_hook || (arc.parallel_threads || []).length) {
          children.push(rtlHeading(`من رواية: ${ntitle}`, HeadingLevel.HEADING_2));
          children.push(rtlPara("الافتتاحية والخطاف", arc.opening_hook || ""));
          for (const th of arc.parallel_threads || []) {
            children.push(rtlPara(`خيط (${th.name || ""})`, th.progression || "", true));
          }
          children.push(rtlPara("ذروة التصادم", arc.climax_collision || ""));
          if (arc.open_threads) children.push(rtlPara("الخيوط المفتوحة", arc.open_threads));
        }
      } else if (sid === "foreshadowing") {
        const items = sec.section_4_foreshadowing || [];
        if (items.length) {
          children.push(rtlHeading(`من رواية: ${ntitle}`, HeadingLevel.HEADING_2));
          items.forEach((it, i) => {
            children.push(rtlHeading(`${i + 1}) ${it.title || ""}`, HeadingLevel.HEADING_3));
            children.push(rtlPara("البذرة المبكرة", it.early_seed || "", true));
            children.push(rtlPara("التمويه", it.camouflage_method || "", true));
            children.push(rtlPara("التفجير والحصاد", it.payoff_twist || "", true));
          });
        }
      } else if (sid === "abstract_blueprints") {
        const bp = sec.section_5_blueprint || {};
        if (bp.summary_flow || (bp.stages || []).length) {
          children.push(rtlHeading(`من رواية: ${ntitle}`, HeadingLevel.HEADING_2));
          children.push(rtlPara("المسار القياسي", bp.summary_flow || ""));
          for (const st of bp.stages || []) {
            children.push(
              rtlPara(
                `المرحلة ${st.stage_num || ""}: ${st.stage_name || ""}`,
                `${st.engineering || ""} — التوجيه والكسر: ${st.expectation_vs_twist || ""}`,
                true
              )
            );
          }
          if (bp.mutation_70_example) children.push(rtlPara("التطبيق المحوّر 70%", bp.mutation_70_example));
        }
      } else if (sid === "system_laws") {
        const sl = sec.section_6_system_laws || {};
        if (Object.keys(sl).length) {
          children.push(rtlHeading(`من رواية: ${ntitle}`, HeadingLevel.HEADING_2));
          const mapLabels = [
            ["mechanics", "آليات العمل"],
            ["costs_and_side_effects", "التكلفة والآثار الجانبية"],
            ["weaknesses_and_balance", "نقاط الضعف والتوازن"],
            ["resource_economy", "اقتصاد الموارد والندرة"],
          ];
          for (const [k, lbl] of mapLabels) {
            const vals = sl[k] || [];
            if (vals.length) {
              children.push(rtlHeading(lbl, HeadingLevel.HEADING_3));
              for (const v of vals) children.push(rtlPara("", v, true));
            }
          }
          const muts = sl.mutations_70 || [];
          if (muts.length) {
            children.push(rtlHeading("تحوير الآليات 70%", HeadingLevel.HEADING_3));
            for (const m of muts) {
              children.push(
                rtlPara(
                  `${m.mutated_name || ""} (عن: ${m.original_name || ""})`,
                  `${m.new_mechanism || ""} — القيد القاتل: ${m.fatal_cost || ""}`,
                  true
                )
              );
            }
          }
        }
      } else if (sid === "micro_tactics") {
        const items = sec.section_7_micro_tactics || [];
        if (items.length) {
          children.push(rtlHeading(`من رواية: ${ntitle}`, HeadingLevel.HEADING_2));
          for (const it of items) {
            children.push(rtlHeading(it.name || "", HeadingLevel.HEADING_3));
            children.push(rtlPara("الموقف المرجعي", it.reference_scene || "", true));
            children.push(rtlPara("المعادلة المجردة", it.abstract_equation || "", true));
            children.push(rtlPara("خطوات التنفيذ", it.execution_steps || "", true));
            children.push(rtlPara("شرط النجاح", it.success_condition || "", true));
            children.push(rtlPara("ثغرة الفشل", it.failure_risk || "", true));
          }
        }
      } else if (sid === "sensory_lexicon") {
        const cats = sec.section_8_sensory_lexicon || [];
        if (cats.length) {
          children.push(rtlHeading(`من رواية: ${ntitle}`, HeadingLevel.HEADING_2));
          for (const cat of cats) {
            children.push(rtlHeading(cat.category || "", HeadingLevel.HEADING_3));
            for (const it of cat.items || []) {
              children.push(
                rtlPara(it.title || "", `"${it.quote || ""}" — القاعدة الأسلوبية: ${it.stylistic_rule || ""}`, true)
              );
            }
          }
        }
      } else if (sid === "character_dna") {
        const ch = sec.section_9_characters || {};
        const chars = ch.characters || [];
        const muts = ch.mutations_70 || [];
        if (chars.length || muts.length) {
          children.push(rtlHeading(`من رواية: ${ntitle}`, HeadingLevel.HEADING_2));
          for (const c of chars) {
            children.push(rtlHeading(c.name_and_title || "", HeadingLevel.HEADING_3));
            children.push(rtlPara("دلالة الاسم", c.name_symbolism || "", true));
            children.push(rtlPara("القناع الخارجي", c.outer_mask || "", true));
            children.push(rtlPara("الدافع الخفي", c.hidden_motive || "", true));
            children.push(rtlPara("التناقض الداخلي", c.inner_contradiction || "", true));
            children.push(rtlPara("اللازمة المميزة", c.signature_habit || "", true));
            children.push(rtlPara("الخصائص ومسار التحول", c.physical_and_psych_arc || "", true));
          }
          if (muts.length) {
            children.push(rtlHeading("شخصيات مولدة بتحوير 70%", HeadingLevel.HEADING_3));
            for (const m of muts) {
              children.push(
                rtlPara(
                  `${m.new_name_and_title || ""} (عن: ${m.inspired_by || ""})`,
                  `العالم: ${m.target_world || ""} | القناع: ${m.outer_mask || ""} | الدافع: ${m.hidden_motive || ""} | اللازمة: ${m.signature_habit || ""} | الخصائص: ${m.traits || ""}`,
                  true
                )
              );
            }
          }
        }
      }
    }
  }

  const doc = new Document({ sections: [{ children }] });
  return await Packer.toBlob(doc);
}

// ------------------------------------------------------------------
// القسم العاشر: 00_الخلاصة_التوليفية_الشاملة (MD + DOCX)
// ------------------------------------------------------------------
export function buildMetaMarkdown(lensCfg, synData) {
  const md = [
    `# القسم 10: الخلاصة التوليفية الشاملة — ${lensCfg.display_name}`,
    `\n## النظرة البانورامية\n${synData.lens_overview || ""}\n`,
    "## أولاً: القوانين الكبرى المشتركة",
  ];
  (synData.grand_shared_laws || []).forEach((law, i) => {
    md.push(`${i + 1}. **${law.law_title || ""}:** ${law.explanation || ""}\n   - *الروايات الموثقة:* ${(law.documented_novels || []).join("، ")}`);
  });
  md.push("\n## ثانياً: التوليفات المبتكرة الجديدة");
  (synData.innovative_syntheses || []).forEach((inv, i) => {
    md.push(
      `${i + 1}. **${inv.synthesis_name || ""}**\n   - *المعادلة:* \`${inv.formula || ""}\`\n   - *التطبيق العملي:* ${inv.practical_application_for_writers || ""}\n   - *ملهمة من:* ${(inv.inspired_by || []).join("، ")}`
    );
  });
  md.push("\n## ثالثاً: تقصي الاختلاف والتنوع والحالات النادرة");
  (synData.diversity_and_outliers_audit || []).forEach((div, i) => {
    md.push(`${i + 1}. **${div.dimension || ""}:** ${div.spectrum_and_rare_cases || ""}\n   - *الروايات:* ${(div.documented_novels || []).join("، ")}`);
  });
  md.push("\n## رابعاً: أمثلة مركّزة موثّقة بالروايات");
  (synData.concentrated_master_examples || []).forEach((ex, i) => {
    md.push(`${i + 1}. **[${ex.category || ""}] ${ex.title || ""}** (الرواية: ${ex.source_novel || ""})\n   - ${ex.breakdown || ""}`);
  });
  return md.join("\n");
}

export async function buildMetaDocxBlob(lensCfg, synData) {
  const children = [
    rtlHeading(`القسم 10: الخلاصة التوليفية الشاملة — ${lensCfg.display_name}`, HeadingLevel.HEADING_1),
    rtlHeading("النظرة البانورامية", HeadingLevel.HEADING_2),
    rtlPara("", synData.lens_overview || ""),
    rtlHeading("أولاً: القوانين الكبرى المشتركة", HeadingLevel.HEADING_2),
  ];

  (synData.grand_shared_laws || []).forEach((law, i) => {
    children.push(rtlPara(`${i + 1}) ${law.law_title || ""}`, law.explanation || ""));
    children.push(rtlPara("الروايات الموثقة", (law.documented_novels || []).join("، "), true));
  });

  children.push(rtlHeading("ثانياً: التوليفات المبتكرة الجديدة", HeadingLevel.HEADING_2));
  (synData.innovative_syntheses || []).forEach((inv, i) => {
    children.push(rtlHeading(`${i + 1}) ${inv.synthesis_name || ""}`, HeadingLevel.HEADING_3));
    children.push(rtlPara("المعادلة", inv.formula || "", true));
    children.push(rtlPara("التطبيق العملي للكاتب", inv.practical_application_for_writers || "", true));
    children.push(rtlPara("ملهمة من", (inv.inspired_by || []).join("، "), true));
  });

  children.push(rtlHeading("ثالثاً: تقصي الاختلاف والتنوع والحالات النادرة", HeadingLevel.HEADING_2));
  (synData.diversity_and_outliers_audit || []).forEach((div, i) => {
    children.push(rtlPara(`${i + 1}) ${div.dimension || ""}`, div.spectrum_and_rare_cases || ""));
    children.push(rtlPara("الروايات", (div.documented_novels || []).join("، "), true));
  });

  children.push(rtlHeading("رابعاً: أمثلة مركّزة موثّقة بالروايات", HeadingLevel.HEADING_2));
  (synData.concentrated_master_examples || []).forEach((ex, i) => {
    children.push(rtlPara(`${i + 1}) [${ex.category || ""}] ${ex.title || ""} (${ex.source_novel || ""})`, ex.breakdown || ""));
  });

  const doc = new Document({ sections: [{ children }] });
  return await Packer.toBlob(doc);
}

// ------------------------------------------------------------------
// التصدير الشامل + حفظ الأرشيف + النسخ الاحتياطي ZIP
// ------------------------------------------------------------------
export async function exportAllLenses(db, lensesConfig, sectionsOrder, settings, logFn = console.log) {
  const maxWords = Number(settings.exportMaxWordsPerPart || 350000);
  const allArtifacts = [];

  for (const [lid, lensCfg] of Object.entries(lensesConfig)) {
    const novels = await db.getDistilledByLens(lid);
    if (!novels.length) continue;

    await db.clearExportArtifactsForLens(lid);
    const lensFolder = safeFilename(lensCfg.folder_name);
    const parts = splitNovelsIntoParts(novels, maxWords);

    for (let i = 0; i < parts.length; i++) {
      const pNum = String(i + 1).padStart(2, "0");
      const mdText = buildPartMarkdown(lensCfg, i + 1, parts.length, parts[i], sectionsOrder);
      const mdBlob = new Blob([mdText], { type: "text/markdown;charset=utf-8" });
      const docxBlob = await buildPartDocxBlob(lensCfg, i + 1, parts.length, parts[i], sectionsOrder);

      const mdArt = { lensId: lid, lensFolder, filename: `${lensFolder}_الجزء_${pNum}.md`, blob: mdBlob };
      const docxArt = { lensId: lid, lensFolder, filename: `${lensFolder}_الجزء_${pNum}.docx`, blob: docxBlob };
      await db.saveExportArtifact(mdArt);
      await db.saveExportArtifact(docxArt);
      allArtifacts.push(mdArt, docxArt);
    }

    const metaFinal = await db.getMetaFinal(lid);
    if (metaFin