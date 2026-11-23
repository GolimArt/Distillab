import json
import os
from copy import deepcopy

DEFAULT_CONFIG = {
    "project_root_dir": "/content/drive/MyDrive/Distillab_Cloud",
    "inbox_dir_name": "_Inbox_Raw",
    "extra_inbox_dirs": [],
    "cache_dir_name": "_Cache_Text",
    "archive_dir_name": "_Archive_Compressed",
    "trash_dir_name": "_Trash_Review",
    "completed_dir_name": "_Completed_Originals",
    "exports_dir_name": "_Vault_Exports",
    "backups_dir_name": "_Backups",
    "db_filename": "library.db",

    # إعدادات المزودين والنماذج (قابلة للتحديث في أي وقت)
    "active_provider": "gemini",
    "providers": {
        "gemini": {
            "type": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "scout_model": "gemini-2.5-flash",
            "distill_model": "gemini-2.5-flash",
            "meta_model": "gemini-2.5-pro",
            "api_keys": [],
            "rpm_limit": 10,
            "min_delay_sec": 6.5,
            "temperature": 0.25,
            "timeout_sec": 180
        },
        "openai_compatible": {
            "type": "openai",
            "base_url": "https://api.groq.com/openai/v1",
            "scout_model": "llama-3.3-70b-versatile",
            "distill_model": "llama-3.3-70b-versatile",
            "meta_model": "llama-3.3-70b-versatile",
            "api_keys": [],
            "rpm_limit": 20,
            "min_delay_sec": 3.5,
            "temperature": 0.25,
            "timeout_sec": 180
        }
    },

    # إعدادات التقطيع والسياق (للتوافق مع المجاني والمدفوع)
    "chunk_mode": "smart_chunks",        # "smart_chunks" للمجاني أو "full_novel" للمدفوع
    "chunk_max_words": 45000,            # 45 ألف كلمة آمنة لحد TPM في الباقة المجانية
    "full_novel_max_words": 130000,      # أقصى حجم للرواية في وضع السياق الكامل
    "max_novels_per_run": 10,            # عدد الروايات في الدفعة الواحدة (0 = بلا حد)

    # إعدادات القسم 10 والتقسيم التلقائي للتصدير
    "meta_batch_size": 8,                # 8 إلى 10 روايات في كل حزمة للمستوى الأول (Map)
    "export_max_words_per_part": 350000, # التقسيم التلقائي الآمن لـ Word و AI Studio و NotebookLM
    "custom_mutation_target": "",        # إذا تُرك فارغاً يستخدم الهدف الافتراضي للعدسة

    # سياسة ما بعد اكتمال التحليل ("archive_compressed", "move_to_trash", "permanent_delete", "keep")
    "post_complete_action": "archive_compressed",
    "confirm_permanent_delete": False,
    "auto_backup_after_run": True
}


class ConfigManager:
    def __init__(self, base_code_dir=None):
        self.base_code_dir = base_code_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config_path = os.path.join(self.base_code_dir, "config.json")
        self.lenses_path = os.path.join(self.base_code_dir, "lenses.json")
        self.config = self.load_config()
        self.lenses_data = self.load_lenses()

    def _deep_merge(self, default, current):
        result = deepcopy(default)
        for k, v in current.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            merged = self._deep_merge(DEFAULT_CONFIG, loaded)
            return merged
        self.save_config(DEFAULT_CONFIG)
        return deepcopy(DEFAULT_CONFIG)

    def save_config(self, new_config=None):
        if new_config is not None:
            self.config = new_config
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def load_lenses(self):
        if not os.path.exists(self.lenses_path):
            raise FileNotFoundError(f"ملف العدسات غير موجود: {self.lenses_path}")
        with open(self.lenses_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_lenses(self):
        return self.lenses_data.get("lenses", {})

    def get_sections_order(self):
        return self.lenses_data.get("sections_order", [])

    def get_paths(self):
        root = self.config["project_root_dir"]
        paths = {
            "root": root,
            "inbox": os.path.join(root, self.config["inbox_dir_name"]),
            "extra_inboxes": [p for p in self.config.get("extra_inbox_dirs", []) if p and os.path.isdir(p)],
            "cache": os.path.join(root, self.config["cache_dir_name"]),
            "archive": os.path.join(root, self.config["archive_dir_name"]),
            "trash": os.path.join(root, self.config["trash_dir_name"]),
            "completed": os.path.join(root, self.config["completed_dir_name"]),
            "exports": os.path.join(root, self.config["exports_dir_name"]),
            "backups": os.path.join(root, self.config["backups_dir_name"]),
            "db": os.path.join(root, self.config["db_filename"]),
        }
        for key in ("root", "inbox", "cache", "archive", "trash", "completed", "exports", "backups"):
            os.makedirs(paths[key], exist_ok=True)
        return paths

    def get_active_provider_cfg(self):
        name = self.config.get("active_provider", "gemini")
        providers = self.config.get("providers", {})
        if name not in providers:
            raise ValueError(f"المزود '{name}' غير معرف في الإعدادات.")
        return name, providers[name]