import json
import os
import time
import requests


class HFDatasetSync:
    """مزامنة قاعدة البيانات والمخرجات والإعدادات مع Dataset خاص في Hugging Face لحفظ دائم."""

    def __init__(self, log_fn=print):
        self.token = (os.environ.get("HF_TOKEN") or "").strip()
        self.repo_id = (os.environ.get("HF_DATASET_REPO") or "").strip()
        self.log = log_fn
        self.enabled = bool(self.token and self.repo_id)

    def pull_data(self, local_data_dir, code_dir):
        if not self.enabled:
            return False
        try:
            from huggingface_hub import HfApi, snapshot_download

            api = HfApi(token=self.token)
            try:
                api.repo_info(repo_id=self.repo_id, repo_type="dataset")
            except Exception:
                self.log(f"[HF Sync] إنشاء Dataset خاص جديد: {self.repo_id}")
                api.create_repo(repo_id=self.repo_id, repo_type="dataset", private=True, exist_ok=True)
                return False

            files = api.list_repo_files(repo_id=self.repo_id, repo_type="dataset")
            if not any(f != ".gitattributes" and f != "README.md" for f in files):
                self.log("[HF Sync] مستودع التخزين فارغ حالياً — سيبدأ الحفظ بعد أول تشغيل.")
                return False

            os.makedirs(local_data_dir, exist_ok=True)
            snapshot_download(
                repo_id=self.repo_id,
                repo_type="dataset",
                token=self.token,
                local_dir=local_data_dir,
            )

            # استعادة config.json و lenses.json إن حُفظا في الداتاسيت
            for cfg_name in ("config.json", "lenses.json"):
                synced_cfg = os.path.join(local_data_dir, cfg_name)
                target_cfg = os.path.join(code_dir, cfg_name)
                if os.path.exists(synced_cfg):
                    with open(synced_cfg, "rb") as src, open(target_cfg, "wb") as dst:
                        dst.write(src.read())

            self.log("[HF Sync] تمت استعادة قاعدة البيانات والمخرجات بنجاح.")
            return True
        except Exception as exc:
            self.log(f"[HF Sync] تعذر السحب: {exc}")
            return False

    def push_data(self, local_data_dir, code_dir, commit_message="Update Distillab Vault"):
        if not self.enabled:
            return False
        try:
            from huggingface_hub import HfApi

            os.makedirs(local_data_dir, exist_ok=True)
            for cfg_name in ("config.json", "lenses.json"):
                src_cfg = os.path.join(code_dir, cfg_name)
                dst_cfg = os.path.join(local_data_dir, cfg_name)
                if os.path.exists(src_cfg):
                    with open(src_cfg, "rb") as src, open(dst_cfg, "wb") as dst:
                        dst.write(src.read())

            api = HfApi(token=self.token)
            api.upload_folder(
                folder_path=local_data_dir,
                repo_id=self.repo_id,
                repo_type="dataset",
                commit_message=commit_message,
                ignore_patterns=["_Inbox_Raw/*", "_Cache_Text/*", "*.tmp"],
            )
            self.log("[HF Sync] تم حفظ ومزامنة المكتبة في التخزين السحابي الخاص.")
            return True
        except Exception as exc:
            self.log(f"[HF Sync] تعذر الرفع: {exc}")
            return False


class GDriveClient:
    """اتصال دائم بـ Google Drive API عبر Refresh Token دون طلب صلاحية يومي."""

    SUPPORTED_EXTS = (".epub", ".pdf", ".docx", ".txt")

    def __init__(self, log_fn=print):
        self.client_id = (os.environ.get("GDRIVE_CLIENT_ID") or "").strip()
        self.client_secret = (os.environ.get("GDRIVE_CLIENT_SECRET") or "").strip()
        self.refresh_token = (os.environ.get("GDRIVE_REFRESH_TOKEN") or "").strip()
        self.root_folder_id = (os.environ.get("GDRIVE_ROOT_FOLDER_ID") or "").strip()
        self.log = log_fn
        self.enabled = bool(self.client_id and self.client_secret and self.refresh_token)
        self._access_token = ""
        self._token_expiry = 0.0

    def _get_token(self):
        if not self.enabled:
            raise RuntimeError("بيانات ربط Google Drive (Client ID / Secret / Refresh Token) غير مضبوطة في Secrets.")
        if self._access_token and time.time() < (self._token_expiry - 120):
            return self._access_token

        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"فشل تجديد توكن Google Drive: {resp.text[:300]}")
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._access_token

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_token()}"}

    def list_folders(self, query_name=""):
        q = "mimeType='application/vnd.google-apps.folder' and trashed=false"
        if query_name:
            safe_q = query_name.replace("'", "\\'")
            q += f" and name contains '{safe_q}'"
        params = {
            "q": q,
            "fields": "files(id, name, parents)",
            "pageSize": 100,
            "orderBy": "name",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        resp = requests.get("https://www.googleapis.com/drive/v3/files", headers=self._headers(), params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"خطأ في قراءة مجلدات Drive: {resp.text[:300]}")
        return resp.json().get("files", [])

    def list_novel_files(self, folder_id):
        q = f"'{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'"
        files = []
        page_token = None
        while True:
            params = {
                "q": q,
                "fields": "nextPageToken, files(id, name, size)",
                "pageSize": 200,
                "orderBy": "name",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            resp = requests.get("https://www.googleapis.com/drive/v3/files", headers=self._headers(), params=params, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f"خطأ في عرض ملفات المجلد: {resp.text[:300]}")
            data = resp.json()
            for item in data.get("files", []):
                if item["name"].lower().endswith(self.SUPPORTED_EXTS):
                    files.append(item)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return files

    def download_file(self, file_id, dest_path):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"
        with requests.get(url, headers=self._headers(), stream=True, timeout=180) as r:
            if r.status_code != 200:
                raise RuntimeError(f"فشل تحميل الملف من Drive: {r.text[:300]}")
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        return dest_path

    def ensure_subfolder(self, parent_id, folder_name):
        safe_name = folder_name.replace("'", "\\'")
        q = f"name='{safe_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        params = {
            "q": q,
            "fields": "files(id, name)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        resp = requests.get("https://www.googleapis.com/drive/v3/files", headers=self._headers(), params=params, timeout=30)
        if resp.status_code == 200:
            existing = resp.json().get("files", [])
            if existing:
                return existing[0]["id"]

        meta = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        create_resp = requests.post(
            "https://www.googleapis.com/drive/v3/files?supportsAllDrives=true",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=meta,
            timeout=30,
        )
        if create_resp.status_code not in (200, 201):
            raise RuntimeError(f"تعذر إنشاء مجلد في Drive: {create_resp.text[:300]}")
        return create_resp.json()["id"]

    def ensure_project_root(self, folder_name="Distillab_Cloud"):
        if self.root_folder_id:
            return self.root_folder_id
        safe_name = folder_name.replace("'", "\\'")
        q = f"name='{safe_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        resp = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=self._headers(),
            params={"q": q, "fields": "files(id, name)"},
            timeout=30,
        )
        if resp.status_code == 200 and resp.json().get("files"):
            self.root_folder_id = resp.json()["files"][0]["id"]
            return self.root_folder_id

        create_resp = requests.post(
            "https://www.googleapis.com/drive/v3/files",
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"name": folder_name, "mimeType": "application/vnd.google-apps.folder"},
            timeout=30,
        )
        if create_resp.status_code not in (200, 201):
            raise RuntimeError(f"تعذر إنشاء مجلد المشروع في Drive: {create_resp.text[:300]}")
        self.root_folder_id = create_resp.json()["id"]
        return self.root_folder_id

    def upload_or_update_file(self, local_path, parent_id):
        filename = os.path.basename(local_path)
        safe_name = filename.replace("'", "\\'")
        q = f"name='{safe_name}' and '{parent_id}' in parents and trashed=false"
        resp = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=self._headers(),
            params={"q": q, "fields": "files(id)", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"},
            timeout=30,
        )
        existing_id = None
        if resp.status_code == 200 and resp.json().get("files"):
            existing_id = resp.json()["files"][0]["id"]

        with open(local_path, "rb") as f:
            file_bytes = f.read()

        if existing_id:
            up_resp = requests.patch(
                f"https://www.googleapis.com/upload/drive/v3/files/{existing_id}?uploadType=media&supportsAllDrives=true",
                headers={**self._headers(), "Content-Type": "application/octet-stream"},
                data=file_bytes,
                timeout=180,
            )
        else:
            metadata = {"name": filename, "parents": [parent_id]}
            boundary = "distillab_multipart_boundary_9911"
            body = (
                f"--{boundary}\r\n"
                "Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{json.dumps(metadata, ensure_ascii=False)}\r\n"
                f"--{boundary}\r\n"
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--".encode("utf-8")
            up_resp = requests.post(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true",
                headers={**self._headers(), "Content-Type": f"multipart/related; boundary={boundary}"},
                data=body,
                timeout=180,
            )

        if up_resp.status_code not in (200, 201):
            raise RuntimeError(f"فشل رفع '{filename}' إلى Drive: {up_resp.text[:300]}")
        return up_resp.json().get("id")

    def sync_exports_to_drive(self, exports_dir, backups_dir):
        if not self.enabled:
            return 0
        root_id = self.ensure_project_root()
        uploaded = 0

        if os.path.isdir(exports_dir):
            drive_exports_id = self.ensure_subfolder(root_id, "_Vault_Exports")
            for sub in sorted(os.listdir(exports_dir)):
                sub_path = os.path.join(exports_dir, sub)
                if os.path.isdir(sub_path):
                    drive_lens_id = self.ensure_subfolder(drive_exports_id, sub)
                    for fn in sorted(os.listdir(sub_path)):
                        if fn.endswith((".md", ".docx")):
                            self.upload_or_update_file(os.path.join(sub_path, fn), drive_lens_id)
                            uploaded += 1

        if os.path.isdir(backups_dir):
            drive_backups_id = self.ensure_subfolder(root_id, "_Backups")
            backups = sorted(
                [os.path.join(backups_dir, f) for f in os.listdir(backups_dir) if f.endswith(".zip")],
                key=os.path.getmtime,
                reverse=True,
            )[:2]
            for bpath in backups:
                self.upload_or_update_file(bpath, drive_backups_id)
                uploaded += 1

        self.log(f"[Drive Sync] تم رفع/تحديث {uploaded} ملف إلى Google Drive بنجاح.")
        return uploaded