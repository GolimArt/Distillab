window.DistillabPrompts = (() => {
  const SYSTEM =
    "أنت مهندس سردي عكسي ومحلل أدبي متخصص في تفكيك الروايات للكتّاب المحترفين. " +
    "استخرج البيانات المعمارية والنفسية والأسلوبية بدقة جراحية دون مقدمات أو خاتمات أو جمل محادثة. " +
    "أرجع JSON صحيحاً فقط يطابق القالب المطلوب تماماً، باللغة العربية الفصحى، مع توثيق الفصول أو السياق من النص فقط.";

  function buildScout(fileName, stats, sampleText, lensesDict) {
    const lensesBlock = Object.entries(lensesDict)
      .map(([id, info]) => `- ${id}: ${info.display_name} — ${info.description}`)
      .join("\n");

    return `افحص مقتطفات الرواية لتحديد هويتها وتصنيفها.
اسم الملف: ${fileName}
الإحصاءات: ${stats.word_count} كلمة | ${stats.char_count} حرف | ${stats.chapter_count} فصل مقدّر

العدسات المتاحة (اختر معرفاً واحداً لـ primary_lens):
${lensesBlock}

أرجع JSON مطابقاً تماماً:
{
  "title": "العنوان النظيف للرواية",
  "author": "اسم المؤلف أو غير معروف",
  "series_name": "اسم السلسلة إن كانت مجلداً من سلسلة، أو نصاً فارغاً للمستقلة",
  "volume_number": 0,
  "primary_lens": "معرف العدسة",
  "sub_tags": ["وسم1", "وسم2", "وسم3", "وسم4"],
  "synopsis": "ملخص مكثف من 3 أسطر"
}

النص العيّني:
${sampleText}`;
  }

  function buildFullPassA(title, lensCfg, text) {
    return `حلل رواية "${title}" وفق عدسة [${lensCfg.display_name}].
توجيه العدسة: ${lensCfg.focus_instructions}

استخرج بتفصيل دون اختصار:
1. section_1_philosophy: أقوى 25 إلى 40 مقولة أو حكمة أو مثل أو فكرة نفسية/فلسفية.
2. section_2_dialogues: 5 إلى 7 من أذكى المواقف الحوارية (السطح مقابل العمق الباطني والتكتيك).
3. section_8_sensory_lexicon: 30 إلى 40 تركيباً وتشبيهاً حسياً وحركياً (Show, Don't Tell) مصنفة في قوائم.

أرجع JSON مطابقاً:
{
  "section_1_philosophy": [
    {"quote": "...", "chapter_context": "...", "theme": "...", "psychological_rule": "...", "narrative_function": "..."}
  ],
  "section_2_dialogues": [
    {"title": "...", "chapter_context": "...", "spoken_surface": "...", "hidden_subtext": "...", "tactic_name": "...", "tactical_breakdown": "..."}
  ],
  "section_8_sensory_lexicon": [
    {"category": "اسم الفئة", "items": [{"title": "...", "quote": "...", "stylistic_rule": "..."}]}
  ]
}

النص الكامل:
${text}`;
  }

  function buildFullPassB(title, lensCfg, mutationTarget, text) {
    return `حلل الهندسة المعمارية لرواية "${title}" وفق عدسة [${lensCfg.display_name}].
توجيه العدسة: ${lensCfg.focus_instructions}

أرجع JSON مطابقاً:
{
  "section_3_arc_structure": {
    "opening_hook": "الافتتاحية والوعد الدرامي",
    "parallel_threads": [{"name": "اسم الخيط", "progression": "تطوره حتى النهاية"}],
    "climax_collision": "تصادم الخيوط في الذروة النهائية",
    "open_threads": "الخيوط المفتوحة"
  },
  "section_4_foreshadowing": [
    {"title": "...", "early_seed": "التفصيل المبكر والفصل", "camouflage_method": "أسلوب التمويه", "payoff_twist": "التفجير/الحصاد"}
  ],
  "section_5_blueprint": {
    "summary_flow": "[المرحلة 1] --> [المرحلة 2] --> [المرحلة 3] --> [المرحلة 4] --> [المرحلة 5]",
    "stages": [{"stage_num": 1, "stage_name": "...", "engineering": "...", "expectation_vs_twist": "..."}],
    "mutation_70_example": "تطبيق القالب محوراً بنسبة 70% لبيئة: ${mutationTarget}"
  }
}

النص الكامل:
${text}`;
  }

  function buildFullPassC(title, lensCfg, mutationTarget, text) {
    return `حلل الأنظمة والتكتيكات والشخصيات في رواية "${title}" وفق عدسة [${lensCfg.display_name}].
القسم 6 (${lensCfg.section_6_title}): ${lensCfg.section_6_focus}
القسم 7 (${lensCfg.section_7_title}): ${lensCfg.section_7_focus}

أرجع JSON مطابقاً:
{
  "section_6_system_laws": {
    "mechanics": ["..."],
    "costs_and_side_effects": ["..."],
    "weaknesses_and_balance": ["..."],
    "resource_economy": ["..."],
    "mutations_70": [{"original_name": "...", "mutated_name": "...", "new_mechanism": "...", "fatal_cost": "..."}]
  },
  "section_7_micro_tactics": [
    {"name": "...", "reference_scene": "...", "abstract_equation": "الطرف أ --> الفعل --> الطرف ب --> النتيجة", "execution_steps": "...", "success_condition": "...", "failure_risk": "..."}
  ],
  "section_9_characters": {
    "characters": [
      {"name_and_title": "...", "name_symbolism": "...", "outer_mask": "...", "hidden_motive": "...", "inner_contradiction": "...", "signature_habit": "...", "physical_and_psych_arc": "..."}
    ],
    "mutations_70": [
      {"inspired_by": "...", "new_name_and_title": "...", "target_world": "${mutationTarget}", "outer_mask": "...", "hidden_motive": "...", "signature_habit": "...", "traits": "..."}
    ]
  }
}

النص الكامل:
${text}`;
  }

  function buildChunkDigest(title, lensCfg, idx, total, chunkText) {
    return `هذا المقطع (${idx + 1} من ${total}) من رواية "${title}" وفق عدسة [${lensCfg.display_name}].
توجيه: ${lensCfg.focus_instructions}

أرجع JSON مطابقاً:
{
  "plot_events_digest": "ملخص أحداث المقطع بالترتيب",
  "threads_seen": ["خيط سردي وتطوره هنا"],
  "seeds_and_reveals": ["بذرة/دليل أو كشف حدث هنا"],
  "philosophy_quotes": [{"quote": "...", "chapter_context": "...", "theme": "...", "psychological_rule": "...", "narrative_function": "..."}],
  "dialogues": [{"title": "...", "chapter_context": "...", "spoken_surface": "...", "hidden_subtext": "...", "tactic_name": "...", "tactical_breakdown": "..."}],
  "sensory_items": [{"category": "الفئة", "title": "...", "quote": "...", "stylistic_rule": "..."}],
  "system_rules_notes": ["قاعدة أو قيد أو تكلفة ظهرت هنا"],
  "tactics_notes": ["خدعة أو خطة مجردة ظهرت هنا"],
  "character_notes": ["اسم الشخصية: القناع/الدافع/اللازمة/التحول"]
}

نص المقطع:
${chunkText}`;
  }

  function buildSynthPlot(title, lensCfg, mutationTarget, digestsText) {
    return `بناءً على خلاصات جميع مقاطع رواية "${title}" من البداية إلى النهاية وفق عدسة [${lensCfg.display_name}]، ابنِ التحليل المعماري الكامل (اربط البذور المبكرة بالانكشافات النهائية).

أرجع JSON مطابقاً:
{
  "section_3_arc_structure": {
    "opening_hook": "...",
    "parallel_threads": [{"name": "...", "progression": "..."}],
    "climax_collision": "...",
    "open_threads": "..."
  },
  "section_4_foreshadowing": [
    {"title": "...", "early_seed": "...", "camouflage_method": "...", "payoff_twist": "..."}
  ],
  "section_5_blueprint": {
    "summary_flow": "[المرحلة 1] --> [المرحلة 2] --> [المرحلة 3] --> [المرحلة 4] --> [المرحلة 5]",
    "stages": [{"stage_num": 1, "stage_name": "...", "engineering": "...", "expectation_vs_twist": "..."}],
    "mutation_70_example": "تطبيق محوّر 70% لبيئة: ${mutationTarget}"
  }
}

الخلاصات:
${digestsText}`;
  }

  function buildSynthSystemsChars(title, lensCfg, mutationTarget, digestsText) {
    return `بناءً على ملاحظات جميع مقاطع رواية "${title}" وفق عدسة [${lensCfg.display_name}]:
القسم 6 (${lensCfg.section_6_title}): ${lensCfg.section_6_focus}
القسم 7 (${lensCfg.section_7_title}): ${lensCfg.section_7_focus}

أرجع JSON مطابقاً للأقسام 6 و 7 و 9 دون تكرار:
{
  "section_6_system_laws": {
    "mechanics": ["..."],
    "costs_and_side_effects": ["..."],
    "weaknesses_and_balance": ["..."],
    "resource_economy": ["..."],
    "mutations_70": [{"original_name": "...", "mutated_name": "...", "new_mechanism": "...", "fatal_cost": "..."}]
  },
  "section_7_micro_tactics": [
    {"name": "...", "reference_scene": "...", "abstract_equation": "الطرف أ --> الفعل --> الطرف ب --> النتيجة", "execution_steps": "...", "success_condition": "...", "failure_risk": "..."}
  ],
  "section_9_characters": {
    "characters": [
      {"name_and_title": "...", "name_symbolism": "...", "outer_mask": "...", "hidden_motive": "...", "inner_contradiction": "...", "signature_habit": "...", "physical_and_psych_arc": "..."}
    ],
    "mutations_70": [
      {"inspired_by": "...", "new_name_and_title": "...", "target_world": "${mutationTarget}", "outer_mask": "...", "hidden_motive": "...", "signature_habit": "...", "traits": "..."}
    ]
  }
}

الملاحظات:
${digestsText}`;
  }

  function buildMetaBatch(lensCfg, batchIndex, compactSummaries) {
    return `الحزمة رقم (${batchIndex + 1}) لمجموعة روايات ضمن [${lensCfg.display_name}].
نفّذ المستوى الأول (Map) من القسم 10:
{
  "batch_novels": ["..."],
  "shared_patterns": [{"pattern_name": "...", "description": "...", "appearing_in": ["..."]}],
  "composite_ideas": [{"idea_title": "...", "how_elements_combine": "...", "source_novels": ["..."]}],
  "rare_outliers": [{"outlier_title": "...", "why_unique": "...", "source_novel": "..."}],
  "key_examples": [{"concept": "...", "documented_example": "..."}]
}

البيانات:
${JSON.stringify(compactSummaries, null, 1)}`;
  }

  function buildMetaFinal(lensCfg, totalCount, batchSyntheses) {
    return `خلاصات المستوى الأول لـ (${totalCount}) رواية في [${lensCfg.display_name}].
نفّذ المستوى الثاني (Reduce) للقسم 10 (الخلاصة التوليفية الشاملة):
{
  "lens_overview": "...",
  "grand_shared_laws": [{"law_title": "...", "explanation": "...", "documented_novels": ["..."]}],
  "innovative_syntheses": [{"synthesis_name": "...", "formula": "...", "practical_application_for_writers": "...", "inspired_by": ["..."]}],
  "diversity_and_outliers_audit": [{"dimension": "...", "spectrum_and_rare_cases": "...", "documented_novels": ["..."]}],
  "concentrated_master_examples": [{"category": "...", "title": "...", "breakdown": "...", "source_novel": "..."}]
}

الحزم:
${JSON.stringify(batchSyntheses, null, 1)}`;
  }

  return {
    SYSTEM,
    buildScout,
    buildFullPassA,
    buildFullPassB,
    buildFullPassC,
    buildChunkDigest,
    buildSynthPlot,
    buildSynthSystemsChars,
    buildMetaBatch,
    buildMetaFinal
  };
})();