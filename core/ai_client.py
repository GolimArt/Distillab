import json
import re
import time
import requests


class DailyQuotaExhaustedError(Exception):
    """يُطلق عند نفاد الحصة اليومية لجميع المفاتيح المتاحة حتى يتوقف البرنامج بأمان."""


class AIContentBlockedError(Exception):
    """يُطلق إذا رفض المزود معالجة مقطع معين لأسباب سياسات المحتوى."""


def parse_json_response(raw_text):
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("استجابة فارغة من النموذج.")

    # إزالة أسيجة الماركداون إن وُجدت
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # استخراج أول كائن أو مصفوفة JSON صالحة
    start_obj = text.find("{")
    end_obj = text.rfind("}")
    if start_obj != -1 and end_obj > start_obj:
        candidate = text[start_obj:end_obj + 1]
        # إزالة الفواصل الزائدة قبل الأقواس المغلقة
        candidate_clean = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(candidate_clean)
        except json.JSONDecodeError:
            pass

    start_arr = text.find("[")
    end_arr = text.rfind("]")
    if start_arr != -1 and end_arr > start_arr:
        candidate = re.sub(r",\s*([}\]])", r"\1", text[start_arr:end_arr + 1])
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"تعذر تحويل رد النموذج إلى JSON صالح. مقتطف:\n{text[:400]}")


class UniversalAIClient:
    def __init__(self, provider_name, provider_cfg, log_fn=print):
        self.provider_name = provider_name
        self.cfg = provider_cfg
        self.log = log_fn
        self.api_keys = [k.strip() for k in provider_cfg.get("api_keys", []) if k and k.strip()]
        if not self.api_keys:
            raise ValueError(f"لا توجد مفاتيح API مضافة للمزود '{provider_name}'. أضف مفتاحاً واحداً على الأقل.")

        self.current_key_idx = 0
        self.exhausted_keys = set()
        self.last_call_ts = {}

    def _wait_rate_limit(self, key):
        min_delay = float(self.cfg.get("min_delay_sec", 6.5))
        last = self.last_call_ts.get(key, 0.0)
        elapsed = time.time() - last
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        self.last_call_ts[key] = time.time()

    def _next_available_key(self):
        total = len(self.api_keys)
        for offset in range(total):
            idx = (self.current_key_idx + offset) % total
            if idx not in self.exhausted_keys:
                self.current_key_idx = idx
                return idx, self.api_keys[idx]
        raise DailyQuotaExhaustedError("تم استنفاد الحصة اليومية لجميع مفاتيح الـ API المتاحة. توقف آمن.")

    def _rotate_key_after_exhaustion(self, failed_idx):
        self.exhausted_keys.add(failed_idx)
        if len(self.exhausted_keys) >= len(self.api_keys):
            raise DailyQuotaExhaustedError("تم استنفاد الحصة اليومية لجميع مفاتيح الـ API. أكمل في الجلسة القادمة.")
        self.current_key_idx = (failed_idx + 1) % len(self.api_keys)
        self.log(f"[تدوير المفاتيح] الانتقال للمفتاح رقم {self.current_key_idx + 1}...")

    def _call_gemini(self, api_key, model, system_prompt, user_prompt, json_mode=True):
        base_url = self.cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        url = f"{base_url}/models/{model}:generateContent?key={api_key}"
        gen_cfg = {
            "temperature": float(self.cfg.get("temperature", 0.25))
        }
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": gen_cfg
        }
        timeout = int(self.cfg.get("timeout_sec", 180))
        resp = requests.post(url, json=payload, timeout=timeout)

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:600]}")

        data = resp.json()
        prompt_fb = data.get("promptFeedback", {})
        if prompt_fb.get("blockReason"):
            raise AIContentBlockedError(f"تم حجب الطلب: {prompt_fb.get('blockReason')}")

        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"لا توجد مخرجات من Gemini: {str(data)[:400]}")

        cand = candidates[0]
        finish_reason = cand.get("finishReason", "")
        if finish_reason in ("SAFETY", "PROHIBITED_CONTENT", "RECITATION", "BLOCKLIST"):
            raise AIContentBlockedError(f"تم حجب المخرج لسبب: {finish_reason}")

        parts = cand.get("content", {}).get("parts", [])
        # استبعاد أجزاء التفكير الداخلي (thought: True) إن وُجدت في نماذج 2.5
        text_parts = [p.get("text", "") for p in parts if not p.get("thought") and "text" in p]
        return "\n".join(text_parts).strip()

    def _call_openai_compatible(self, api_key, model, system_prompt, user_prompt, json_mode=True):
        base_url = self.cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "temperature": float(self.cfg.get("temperature", 0.25)),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        timeout = int(self.cfg.get("timeout_sec", 180))
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)

        # إذا كان النموذج لا يدعم response_format
        if resp.status_code == 400 and json_mode and "response_format" in resp.text:
            payload.pop("response_format", None)
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:600]}")

        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    def generate_json(self, model, system_prompt, user_prompt, max_retries=4):
        ptype = self.cfg.get("type", "gemini")
        last_err = None

        for attempt in range(1, max_retries + 1):
            key_idx, api_key = self._next_available_key()
            self._wait_rate_limit(api_key)

            try:
                if ptype == "gemini":
                    raw = self._call_gemini(api_key, model, system_prompt, user_prompt, json_mode=True)
                else:
                    raw = self._call_openai_compatible(api_key, model, system_prompt, user_prompt, json_mode=True)
                return parse_json_response(raw)

            except DailyQuotaExhaustedError:
                raise
            except AIContentBlockedError:
                raise
            except Exception as exc:
                msg = str(exc)
                last_err = exc
                lower_msg = msg.lower()

                # خطأ مفتاح غير صالح أو محظور
                if "http 401" in lower_msg or "http 403" in lower_msg or "api_key_invalid" in lower_msg:
                    self.log(f"[تحذير] المفتاح رقم {key_idx + 1} غير صالح أو مرفوض. تخطي المفتاح.")
                    self._rotate_key_after_exhaustion(key_idx)
                    continue

                # حدود المعدل أو الحصة اليومية
                if "http 429" in lower_msg or "resource_exhausted" in lower_msg or "rate_limit" in lower_msg:
                    is_daily = any(tok in lower_msg for tok in ("perday", "per_day", "daily", "quota exceeded for metric"))
                    if is_daily:
                        self.log(f"[تنبيه الحصة] نفدت الحصة اليومية للمفتاح رقم {key_idx + 1}.")
                        self._rotate_key_after_exhaustion(key_idx)
                        continue
                    wait_sec = min(65, 15 * attempt)
                    self.log(f"[منظّم السرعة] ضغط 429 (محاولة {attempt}/{max_retries}) — انتظار {wait_sec} ثانية...")
                    time.sleep(wait_sec)
                    if attempt == max_retries:
                        self._rotate_key_after_exhaustion(key_idx)
                    continue

                # أخطاء شبكة أو JSON غير مكتمل: إعادة المحاولة
                wait_sec = min(25, 5 * attempt)
                self.log(f"[إعادة محاولة {attempt}/{max_retries}] خطأ مؤقت: {msg[:180]}")
                time.sleep(wait_sec)

        raise RuntimeError(f"فشل الطلب بعد {max_retries} محاولات: {last_err}")