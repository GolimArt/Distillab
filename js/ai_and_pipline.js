class DailyQuotaExhaustedError extends Error {
  constructor(msg) { super(msg); this.name = "DailyQuotaExhaustedError"; }
}
class AIContentBlockedError extends Error {
  constructor(msg) { super(msg); this.name = "AIContentBlockedError"; }
}
class RunAbortedError extends Error {
  constructor(msg = "تم إيقاف التشغيل بأمان بناءً على طلبك.") { super(msg); this.name = "RunAbortedError"; }
}

function parseJsonResponse(rawText) {
  let text = (rawText || "").trim();
  if (!text) throw new Error("استجابة فارغة من النموذج.");
  text = text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "").trim();

  try { return JSON.parse(text); } catch {}

  const sObj = text.indexOf("{");
  const eObj = text.lastIndexOf("}");
  if (sObj !== -1 && eObj > sObj) {
    const cand = text.slice(sObj, eObj + 1).replace(/,\s*([}\]])/g, "$1");
    try { return JSON.parse(cand); } catch {}
  }

  const sArr = text.indexOf("[");
  const eArr = text.lastIndexOf("]");
  if (sArr !== -1 && eArr > sArr) {
    const cand = text.slice(sArr, eArr + 1).replace(/,\s*([}\]])/g, "$1");
    try { return JSON.parse(cand); } catch {}
  }

  throw new Error("تعذر تحليل رد النموذج إلى JSON صالح: " + text.slice(0, 260));
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

class BrowserAIClient {
  constructor(providerName, providerCfg, logFn = console.log, shouldStopFn = () => false) {
    this.providerName = providerName;
    this.cfg = providerCfg;
    this.log = logFn;
    this.shouldStop = shouldStopFn;
    this.apiKeys = (providerCfg.api_keys || []).map((k) => k.trim()).filter(Boolean);
    if (!this.apiKeys.length) {
      throw new Error(`لا توجد مفاتيح API مضافة للمزود (${providerName}). أضف مفتاحاً في الإعدادات.`);
    }
    this.currentKeyIdx = 0;
    this.exhaustedKeys = new Set();
    this.lastCallTs = {};
  }

  async _waitRateLimit(key) {
    const minDelayMs = Number(this.cfg.min_delay_sec || 6.5) * 1000;
    const last = this.lastCallTs[key] || 0;
    const wait = minDelayMs - (Date.now() - last);
    if (wait > 0) await sleep(wait);
    if (this.shouldStop()) throw new RunAbortedError();
    this.lastCallTs[key] = Date.now();
  }

  _nextAvailableKey() {
    for (let off = 0; off < this.apiKeys.length; off++) {
      const idx = (this.currentKeyIdx + off) % this.apiKeys.length;
      if (!this.exhaustedKeys.has(idx)) {
        this.currentKeyIdx = idx;
        return { idx, key: this.apiKeys[idx] };
      }
    }
    throw new DailyQuotaExhaustedError("تم استنفاد الحصة اليومية لجميع المفاتيح المتاحة. توقف آمن.");
  }

  _rotateExhaustedKey(failedIdx) {
    this.exhaustedKeys.add(failedIdx);
    if (this.exhaustedKeys.size >= this.apiKeys.length) {
      throw new DailyQuotaExhaustedError("تم استنفاد الحصة اليومية لجميع المفاتيح. استأنف في الجلسة القادمة.");
    }
    this.currentKeyIdx = (failedIdx + 1) % this.apiKeys.length;
    this.log(`[تدوير المفاتيح] الانتقال للمفتاح رقم ${this.currentKeyIdx + 1}...`);
  }

  async _callGemini(apiKey, model, systemPrompt, userPrompt) {
    const baseUrl = (this.cfg.base_url || "https://generativelanguage.googleapis.com/v1beta").replace(/\/+$/, "");
    const url = `${baseUrl}/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(apiKey)}`;
    const payload = {
      systemInstruction: { parts: [{ text: systemPrompt }] },
      contents: [{ role: "user", parts: [{ text: userPrompt }] }],
      generationConfig: {
        temperature: Number(this.cfg.temperature ?? 0.25),
        responseMimeType: "application/json"
      }
    };
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const text = await resp.text();
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${text.slice(0, 500)}`);

    const data = JSON.parse(text);
    if (data.promptFeedback?.blockReason) {
      throw new AIContentBlockedError(`تم حجب الطلب: ${data.promptFeedback.blockReason}`);
    }
    const cand = data.candidates?.[0];
    if (!cand) throw new Error("لا توجد مخرجات من Gemini.");
    if (["SAFETY", "PROHIBITED_CONTENT", "RECITATION", "BLOCKLIST"].includes(cand.finishReason)) {
      throw new AIContentBlockedError(`تم حجب المخرج: ${cand.finishReason}`);
    }
    const parts = cand.content?.parts || [];
    return parts.filter((p) => !p.thought && typeof p.text === "string").map((p) => p.text).join("\n").trim();
  }

  async _callOpenAI(apiKey, model, systemPrompt, userPrompt) {
    const baseUrl = (this.cfg.base_url || "https://api.openai.com/v1").replace(/\/+$/, "");
    const url = `${baseUrl}/chat/completions`;
    const body = {
      model,
      temperature: Number(this.cfg.temperature ?? 0.25),
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: userPrompt }
      ],
      response_format: { type: "json_object" }
    };
    let resp = await fetch(url, {
      method: "POST",
      headers: { "Authorization": `Bearer ${apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    let text = await resp.text();
    if (resp.status === 400 && text.includes("response_format")) {
      delete body.response_format;
      resp = await fetch(url, {
        method: "POST",
        headers: { "Authorization": `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      text = await resp.text();
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${text.slice(0, 500)}`);
    const data = JSON.parse(text);
    return data.choices[0].message.content.trim();
  }

  async generateJson(model, systemPrompt, userPrompt, maxRetries = 4) {
    const ptype = this.cfg.type || "gemini";
    let lastErr = null;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      if (this.shouldStop()) throw new RunAbortedError();
      const { idx, key } = this._nextAvailableKey();
      await this._waitRateLimit(key);

      try {
        const raw = ptype === "gemini"
          ? await this._callGemini(key, model, systemPrompt, userPrompt)
          : await this._callOpenAI(key, model, systemPrompt, userPrompt);
        return parseJsonResponse(raw);
      } catch (err) {
        if (err instanceof DailyQuotaExhaustedError || err instanceof AIContentBlockedError || err instanceof RunAbortedError) {
          throw err;
        }
        lastErr = err;
        const msg = (err.message || "").toLowerCase();

        if (msg.includes("http 401") || msg.includes("http 403") || msg.includes("api_key_invalid")) {
          this.log(`[تحذير] المفتاح ${idx + 1} غير صالح أو مرفوض. تخطي.`);
          this._rotateExhaustedKey(idx);
          continue;
        }
        if (msg.includes("http 429") || msg.includes("resource_exhausted") || msg.includes("rate_limit")) {
          if (msg.includes("perday") || msg.includes("per_day") || msg.includes("daily")) {
            this.log(`[الحصة] نفدت الحصة اليومية للمفتاح ${idx + 1}.`);
            this._rotateExhaustedKey(idx);
            continue;
          }
          const waitSec = Math.min(60, 15 * attempt);
          this.log(`[منظم السرعة] ضغط 429 (محاولة ${attempt}/${maxRetries}) — انتظار ${waitSec} ثانية...`);
          await sleep(waitSec * 1000);
          if (attempt === maxRetries) this._rotateExhaustedKey(idx);
          continue;
        }

        const waitSec = Math.min(20, 5 * attempt);
        this.log(`[إعادة محاولة ${attempt}/${maxRetries}] ${err.message.slice(0, 160)}`);
        await sleep(waitSec * 1000);
      }
    }
    throw new Error(`فشل الطلب بعد ${maxRetries} محاولات: ${lastErr?.message}`);
  }
}

window.DistillabAI = {
  BrowserAIClient,
  DailyQuotaExhaustedError,
  AIContentBlockedError,
  RunAbortedError
};