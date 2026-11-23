import json


SYSTEM_ANALYST_PROMPT = (
    "أنت مهندس سردي عكسي ومحلل أدبي متخصص في تفكيك الروايات للكتّاب المحترفين. "
    "مهمتك استخراج البيانات المعمارية والنفسية والأسلوبية بدقة جراحية دون مقدمات أو خاتمات أو جمل محادثة. "
    "التزم التزاماً صارماً بإرجاع JSON صحيح يطابق البنية المطلوبة فقط، باللغة العربية الفصحى الدقيقة، "
    "مع توثيق أرقام الفصول أو السياقات الحقيقية من النص المرفق فقط دون اختراع أي معلومة."
)


def build_scout_prompt(file_name, stats, sample_text, lenses_dict):
    lenses_desc = []
    for lid, linfo in lenses_dict.items():
        lenses_desc.append(f"- {lid}: {linfo['display_name']} — {linfo['description']}")
    lenses_block = "\n".join(lenses_desc)

    return f"""قم بفحص المقتطفات التالية من الرواية لتحديد هويتها وتصنيفها بدقة.
اسم الملف: {file_name}
الإحصاءات: {stats['word_count']} كلمة | {stats['char_count']} حرف | {stats['chapter_count']} فصل مقدّر

العدسات المتاحة للاختيار (اختر معرفاً واحداً فقط لـ primary_lens):
{lenses_block}

المطلوب إرجاعه بصيغة JSON مطابقة تماماً لهذا القالب:
{{
  "title": "العنوان النظيف للرواية بالعربية",
  "author": "اسم المؤلف أو غير معروف",
  "series_name": "اسم السلسلة إن كانت الرواية مجلداً/جزءاً من سلسلة طويلة، أو اتركه نصاً فارغاً للرواية المستقلة",
  "volume_number": 0,
  "primary_lens": "واحد من معرفات العدسات أعلاه",
  "sub_tags": ["وسم_1", "وسم_2", "وسم_3", "وسم_4"],
  "synopsis": "ملخص مكثف من 3 أسطر لنوع الحبكة والصراع المركزي"
}}

النص العيّني:
{sample_text}"""


# ----------------------------------------------------------------------
# أوامر الرواية الكاملة (3 استدعاءات مركزة لاستخراج 9 أقسام بأعلى عمق)
# ----------------------------------------------------------------------

def build_full_pass_a_prompt(title, lens_cfg, text):
    return f"""حلل رواية "{title}" وفق عدسة [{lens_cfg['display_name']}].
توجيه العدسة: {lens_cfg['focus_instructions']}

امسح النص من أوله إلى آخره واستخرج بدقة وتفصيل دون اختصار:
1. section_1_philosophy: أقوى 25 إلى 40 مقولة أو حكمة أو مثل أو فكرة نفسية/فلسفية حول الطبيعة البشرية والسلطة والمصلحة والبقاء أو موضوع الرواية.
2. section_2_dialogues: 5 إلى 7 من أذكى المواقف الحوارية (السطح المنطوق مقابل العمق الباطني والتكتيك النفسي).
3. section_8_sensory_lexicon: 30 إلى 40 تركيباً وتشبيهاً حسياً وحركياً (Show, Don't Tell) مصنفة في قوائم حسب الحالات الشعورية والمكانية والحركية.

أرجع JSON مطابقاً تماماً لهذا القالب:
{{
  "section_1_philosophy": [
    {{
      "quote": "الاقتباس النصي أو أقرب صياغة دقيقة",
      "chapter_context": "الفصل أو السياق",
      "theme": "المحور الموضوعي",
      "psychological_rule": "القاعدة النفسية أو الفكرية الكامنة",
      "narrative_function": "الوظيفة السردية في الرواية"
    }}
  ],
  "section_2_dialogues": [
    {{
      "title": "عنوان الموقف",
      "chapter_context": "الفصل والأطراف",
      "spoken_surface": "ما قيل باللسان حرفياً",
      "hidden_subtext": "ما أُخفي أو حُسب في العقل/القلب",
      "tactic_name": "اسم التكتيك النفسي أو الدرامي",
      "tactical_breakdown": "شرح آلية نجاح التكتيك"
    }}
  ],
  "section_8_sensory_lexicon": [
    {{
      "category": "اسم الفئة (مثل: الرعب والتوتر / لغة الجسد / البيئة والمكان / الصدمة والكشف / الحركة والألم)",
      "items": [
        {{
          "title": "عنوان مختصر",
          "quote": "الجملة أو التركيب الحسي من النص",
          "stylistic_rule": "القاعدة الأسلوبية التطبيقية"
        }}
      ]
    }}
  ]
}}

النص الكامل:
{text}"""


def build_full_pass_b_prompt(title, lens_cfg, mutation_target, text):
    return f"""حلل الهندسة المعمارية لرواية "{title}" وفق عدسة [{lens_cfg['display_name']}].
توجيه العدسة: {lens_cfg['focus_instructions']}

استخرج بتفصيل تطبيقي:
1. section_3_arc_structure: كيف افتتح الكاتب القصة، جميع الخيوط السردية المتوازية التي فتحها (رئيسية وفرعية)، وكيف اصطدمت في الذروة النهائية (Climax) وانكشف الحل أو المصير.
2. section_4_foreshadowing: 6 إلى 10 أمثلة دقيقة لبذور وتلميحات وأدلة مبكرة زرعها الكاتب ببراءة، وكيف موّهها، وكيف انفجرت لاحقاً.
3. section_5_blueprint: قالب حبكة قياسي مجرد من الأسماء من 5 إلى 6 مراحل، مع تطبيق تحويري بنسبة 70% يناسب "{mutation_target}".

أرجع JSON مطابقاً تماماً لهذا القالب:
{{
  "section_3_arc_structure": {{
    "opening_hook": "تفاصيل الافتتاحية والوعد الدرامي",
    "parallel_threads": [
      {{"name": "اسم الخيط", "progression": "تطوره حتى النهاية"}}
    ],
    "climax_collision": "آلية تصادم الخيوط في الذروة النهائية",
    "open_threads": "الخيوط المفتوحة أو الدلالات الختامية"
  }},
  "section_4_foreshadowing": [
    {{
      "title": "عنوان البذرة",
      "early_seed": "التفصيل المبكر ورقم الفصل",
      "camouflage_method": "كيف صرف الكاتب انتباه القارئ عنها",
      "payoff_twist": "كيف انفجرت لاحقاً كالتواء أو حل"
    }}
  ],
  "section_5_blueprint": {{
    "summary_flow": "[المرحلة 1] --> [المرحلة 2] --> [المرحلة 3] --> [المرحلة 4] --> [المرحلة 5]",
    "stages": [
      {{
        "stage_num": 1,
        "stage_name": "اسم المرحلة المجرد",
        "engineering": "البناء الهندسي للمرحلة",
        "expectation_vs_twist": "كيف توجّه توقعات القارئ ثم تكسرها"
      }}
    ],
    "mutation_70_example": "تطبيق القالب بالكامل محوراً بنسبة 70% لبيئة: {mutation_target}"
  }}
}}

النص الكامل:
{text}"""


def build_full_pass_c_prompt(title, lens_cfg, mutation_target, text):
    return f"""حلل الأنظمة والتكتيكات والشخصيات في رواية "{title}" وفق عدسة [{lens_cfg['display_name']}].
تركيز القسم 6 ({lens_cfg['section_6_title']}): {lens_cfg['section_6_focus']}
تركيز القسم 7 ({lens_cfg['section_7_title']}): {lens_cfg['section_7_focus']}

استخرج:
1. section_6_system_laws: دستور القواعد والقيود والتكلفة ونقاط الضعف واقتصاد الموارد + تحوير 3 آليات/قدرات/قوانين بنسبة 70% لتناسب "{mutation_target}".
2. section_7_micro_tactics: 5 إلى 7 خطط وخدع ومناورات (قتالية أو تحقيقية أو نفسية أو اجتماعية) مجردة من الأسماء كمعادلات تكتيكية.
3. section_9_characters: تشريح أبرز 5 إلى 7 شخصيات وفق معادلة التناقض (الاسم ودلالته + القناع الخارجي + الدافع الخفي + التناقض الداخلي + اللازمة الحركية/البصرية + الخصائص وقوس التحول) + ابتكار شخصيتين جديدتين محورتين بنسبة 70% لبيئة "{mutation_target}".

أرجع JSON مطابقاً تماماً لهذا القالب:
{{
  "section_6_system_laws": {{
    "mechanics": ["قانون/آلية عمل 1", "..."],
    "costs_and_side_effects": ["تكلفة/أثر جانبي قاتل 1", "..."],
    "weaknesses_and_balance": ["نقطة ضعف/قاعدة توازن 1", "..."],
    "resource_economy": ["نظام ندرة أو مقايضة 1", "..."],
    "mutations_70": [
      {{
        "original_name": "اسم الآلية/القدرة الأصلية",
        "mutated_name": "الاسم المحوّر 70%",
        "new_mechanism": "آلية العمل الجديدة",
        "fatal_cost": "القيد القاتل والتكلفة"
      }}
    ]
  }},
  "section_7_micro_tactics": [
    {{
      "name": "اسم القالب التكتيكي",
      "reference_scene": "الموقف المرجعي في الرواية",
      "abstract_equation": "الطرف أ --> الفعل/الحيلة --> الطرف ب --> النتيجة",
      "execution_steps": "خطوات التنفيذ",
      "success_condition": "شرط النجاح",
      "failure_risk": "ثغرة الفشل المحتملة"
    }}
  ],
  "section_9_characters": {{
    "characters": [
      {{
        "name_and_title": "الاسم واللقب",
        "name_symbolism": "دلالة الاسم واللقب",
        "outer_mask": "القناع الخارجي",
        "hidden_motive": "الدافع الجوهري الخفي",
        "inner_contradiction": "معادلة التناقض الداخلي",
        "signature_habit": "اللازمة الحركية/البصرية/اللفظية",
        "physical_and_psych_arc": "الخصائص الفيزيائية والنفسية ومسار التحول"
      }}
    ],
    "mutations_70": [
      {{
        "inspired_by": "الشخصية المستلهم منها",
        "new_name_and_title": "الاسم واللقب الجديد",
        "target_world": "{mutation_target}",
        "outer_mask": "القناع الجديد",
        "hidden_motive": "الدافع الجديد",
        "signature_habit": "اللازمة الجديدة",
        "traits": "الخصائص والجوهر المحفوظ"
      }}
    ]
  }}
}}

النص الكامل:
{text}"""


# ----------------------------------------------------------------------
# أوامر وضع التقطيع الذكي للباقة المجانية والروايات الطويلة (Map -> Synthesize)
# ----------------------------------------------------------------------

def build_chunk_digest_prompt(title, lens_cfg, chunk_idx, total_chunks, chunk_text):
    return f"""هذا هو المقطع رقم ({chunk_idx + 1} من {total_chunks}) من رواية "{title}" وفق عدسة [{lens_cfg['display_name']}].
تركيز العدسة: {lens_cfg['focus_instructions']}

استخرج من هذا المقطع بدقة دون اختلاق أي معلومة:
1. ملخص أحداث هذا المقطع بالترتيب + الخيوط المتوازية + أي تلميحات/أدلة/بذور أو كشف حقائق حدث فيه.
2. 10 إلى 18 مقولة/حكمة من هذا المقطع.
3. 2 إلى 3 مواقف حوارية ذكية من هذا المقطع.
4. 10 إلى 15 تركيباً وتشبيهاً حسياً وحركياً من هذا المقطع.
5. أي قوانين/قيود، تكتيكات/خدع، أو ملاحظات شخصيات بارزة ظهرت في هذا المقطع.

أرجع JSON مطابقاً تماماً لهذا القالب:
{{
  "plot_events_digest": "سرد منظم لأحداث المقطع وأي كشف أو تحول",
  "threads_seen": ["خيط سردي وتطوره في هذا المقطع"],
  "seeds_and_reveals": ["بذرة/دليل مبكر أو انكشاف حدث في هذا المقطع"],
  "philosophy_quotes": [
    {{
      "quote": "الاقتباس",
      "chapter_context": "السياق/الفصل",
      "theme": "المحور",
      "psychological_rule": "القاعدة النفسية",
      "narrative_function": "الوظيفة السردية"
    }}
  ],
  "dialogues": [
    {{
      "title": "عنوان الموقف",
      "chapter_context": "الفصل والأطراف",
      "spoken_surface": "المنطوق",
      "hidden_subtext": "الباطن",
      "tactic_name": "اسم التكتيك",
      "tactical_breakdown": "الشرح"
    }}
  ],
  "sensory_items": [
    {{
      "category": "الفئة الشعورية أو البيئية",
      "title": "عنوان مختصر",
      "quote": "التركيب الحسي",
      "stylistic_rule": "القاعدة الأسلوبية"
    }}
  ],
  "system_rules_notes": ["قاعدة نظام أو تكلفة أو قيد ظهر هنا"],
  "tactics_notes": ["خدعة أو خطة ظهرت هنا بتجريدها"],
  "character_notes": ["اسم الشخصية: القناع/الدافع/اللازمة/التحول في هذا المقطع"]
}}

نص المقطع:
{chunk_text}"""


def build_synthesis_plot_prompt(title, lens_cfg, mutation_target, combined_digests_text):
    return f"""بناءً على الخلاصات المتسلسلة لجميع مقاطع رواية "{title}" من البداية إلى النهاية وفق عدسة [{lens_cfg['display_name']}]، قم ببناء التحليل المعماري الكامل للرواية (اربط البذور المبكرة في المقاطع الأولى بالانكشافات في المقاطع الأخيرة).

أرجع JSON مطابقاً تماماً لهذا القالب:
{{
  "section_3_arc_structure": {{
    "opening_hook": "كيف افتتح الكاتب الرواية والوعد الدرامي",
    "parallel_threads": [
      {{"name": "اسم الخيط", "progression": "مسار تطوره من البداية للنهاية"}}
    ],
    "climax_collision": "كيف تصادمت الخيوط في الذروة النهائية",
    "open_threads": "الخيوط المفتوحة أو الخاتمة"
  }},
  "section_4_foreshadowing": [
    {{
      "title": "عنوان البذرة",
      "early_seed": "التفصيل المبكر",
      "camouflage_method": "طريقة التمويه",
      "payoff_twist": "التفجير أو الكشف النهائي"
    }}
  ],
  "section_5_blueprint": {{
    "summary_flow": "[المرحلة 1] --> [المرحلة 2] --> [المرحلة 3] --> [المرحلة 4] --> [المرحلة 5]",
    "stages": [
      {{
        "stage_num": 1,
        "stage_name": "اسم المرحلة المجرد",
        "engineering": "البناء الهندسي",
        "expectation_vs_twist": "التوجيه وكسر التوقع"
      }}
    ],
    "mutation_70_example": "تطبيق القالب محوراً بنسبة 70% لبيئة: {mutation_target}"
  }}
}}

خلاصات المقاطع المجمعة:
{combined_digests_text}"""


def build_synthesis_systems_chars_prompt(title, lens_cfg, mutation_target, combined_digests_text):
    return f"""بناءً على الملاحظات المجمعة لجميع مقاطع رواية "{title}" وفق عدسة [{lens_cfg['display_name']}]:
تركيز القسم 6 ({lens_cfg['section_6_title']}): {lens_cfg['section_6_focus']}
تركيز القسم 7 ({lens_cfg['section_7_title']}): {lens_cfg['section_7_focus']}

استخرج الأقسام 6 و 7 و 9 كاملةً دون تكرار، وأرجع JSON مطابقاً تماماً لهذا القالب:
{{
  "section_6_system_laws": {{
    "mechanics": ["..."],
    "costs_and_side_effects": ["..."],
    "weaknesses_and_balance": ["..."],
    "resource_economy": ["..."],
    "mutations_70": [
      {{
        "original_name": "...",
        "mutated_name": "...",
        "new_mechanism": "...",
        "fatal_cost": "..."
      }}
    ]
  }},
  "section_7_micro_tactics": [
    {{
      "name": "...",
      "reference_scene": "...",
      "abstract_equation": "الطرف أ --> الفعل --> الطرف ب --> النتيجة",
      "execution_steps": "...",
      "success_condition": "...",
      "failure_risk": "..."
    }}
  ],
  "section_9_characters": {{
    "characters": [
      {{
        "name_and_title": "...",
        "name_symbolism": "...",
        "outer_mask": "...",
        "hidden_motive": "...",
        "inner_contradiction": "...",
        "signature_habit": "...",
        "physical_and_psych_arc": "..."
      }}
    ],
    "mutations_70": [
      {{
        "inspired_by": "...",
        "new_name_and_title": "...",
        "target_world": "{mutation_target}",
        "outer_mask": "...",
        "hidden_motive": "...",
        "signature_habit": "...",
        "traits": "..."
      }}
    ]
  }}
}}

ملاحظات المقاطع المجمعة:
{combined_digests_text}"""


# ----------------------------------------------------------------------
# أوامر القسم العاشر: التوليف الهرمي (Hierarchical Meta-Synthesis)
# ----------------------------------------------------------------------

def build_meta_batch_prompt(lens_cfg, batch_index, compact_novels_summaries):
    payload_str = json.dumps(compact_novels_summaries, ensure_ascii=False, indent=1)
    return f"""هذه هي الحزمة رقم ({batch_index + 1}) وتضم ملخصات تحليلية لمجموعة روايات ضمن [{lens_cfg['display_name']}].
نفّذ المستوى الأول (Map) من القسم العاشر (الخلاصة التوليفية الشاملة):
استخرج الأنماط المشتركة المتكررة بين هذه الروايات، والأفكار التوليفية المركبة، والحالات الشاذة والنادرة التي انفردت بها رواية دون غيرها، مع التوثيق بأسماء الروايات.

أرجع JSON مطابقاً تماماً لهذا القالب:
{{
  "batch_novels": ["اسم رواية 1", "..."],
  "shared_patterns": [
    {{
      "pattern_name": "اسم النمط المشترك",
      "description": "وصف دقيق للنمط وآلية عمله",
      "appearing_in": ["اسم رواية 1", "اسم رواية 2"]
    }}
  ],
  "composite_ideas": [
    {{
      "idea_title": "الفكرة المركبة",
      "how_elements_combine": "كيف تندمج عدة تقنيات معاً",
      "source_novels": ["اسم رواية"]
    }}
  ],
  "rare_outliers": [
    {{
      "outlier_title": "الظاهرة أو الحيلة النادرة",
      "why_unique": "لماذا تخرج عن المألوف وكيف استثمرها الكاتب",
      "source_novel": "اسم الرواية"
    }}
  ],
  "key_examples": [
    {{
      "concept": "المفهوم",
      "documented_example": "مثال مركز موثق باسم الرواية"
    }}
  ]
}}

بيانات الحزمة:
{payload_str}"""


def build_meta_final_prompt(lens_cfg, total_novels_count, batch_syntheses_list):
    payload_str = json.dumps(batch_syntheses_list, ensure_ascii=False, indent=1)
    return f"""أمامك خلاصات المستوى الأول لجميع حزم [{lens_cfg['display_name']}] التي تغطي إجمالاً ({total_novels_count}) رواية.
نفّذ المستوى الثاني (Reduce) لبناء "الخلاصة التوليفية الشاملة" (القسم العاشر) لتكون المرجع الهندسي الأعلى للكاتب عند العمل على هذا التصنيف.

أرجع JSON مطابقاً تماماً لهذا القالب:
{{
  "lens_overview": "نظرة بانورامية شاملة على القواعد الفكرية والمعمارية الحاكمة لهذا التصنيف عبر جميع الروايات ({total_novels_count} رواية)",
  "grand_shared_laws": [
    {{
      "law_title": "القانون الكبير المشترك",
      "explanation": "الشرح الهندسي والتطبيقي للقانون",
      "documented_novels": ["أسماء الروايات الموثقة"]
    }}
  ],
  "innovative_syntheses": [
    {{
      "synthesis_name": "التوليفة المبتكرة الجديدة (دمج أساليب من روايات متعددة)",
      "formula": "المعادلة أو القالب التطبيقي الجديد",
      "practical_application_for_writers": "كيف يوظفه الكاتب في روايته الجديدة",
      "inspired_by": ["أسماء الروايات الملهمة"]
    }}
  ],
  "diversity_and_outliers_audit": [
    {{
      "dimension": "محور التنوع (مثل: أنماط الجناة / حلول الألغاز / الدوافع / الخاتمات)",
      "spectrum_and_rare_cases": "تقصي الاختلافات والحالات النادرة الشاذة التي تمنع التكرار",
      "documented_novels": ["أسماء الروايات"]
    }}
  ],
  "concentrated_master_examples": [
    {{
      "category": "التصنيف (حبكة / خدعة / حوار / شخصية / بذرة)",
      "title": "عنوان المثال النموذجي",
      "breakdown": "خلاصة مركزة قابلة للتطبيق المباشر",
      "source_novel": "اسم الرواية"
    }}
  ]
}}

خلاصات الحزم:
{payload_str}"""
