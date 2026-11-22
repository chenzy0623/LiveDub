"""机器翻译：多后端可切换。

后端：
  bing     免费（cn.bing.com 网页接口，无需 Key，国内可用）
  deepseek DeepSeek 官方 API（需 Key，质量最好）
  openai   任意 OpenAI 兼容接口（通义/Kimi/智谱/硅基流动…）
  nllb     本地离线模型（ctranslate2，可选）
  none     直通（调试用）
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Optional

import requests

# 统一语言代码
LANG_ALIAS = {
    "zh": "zh-Hans", "zh-cn": "zh-Hans", "zh-hans": "zh-Hans", "chinese": "zh-Hans",
    "zh-tw": "zh-Hant", "cht": "zh-Hant",
    "en": "en", "english": "en", "ja": "ja", "jp": "ja", "ko": "ko", "kr": "ko",
    "fr": "fr", "de": "de", "es": "es", "ru": "ru", "pt": "pt", "it": "it",
    "ar": "ar", "th": "th", "vi": "vi", "id": "id", "tr": "tr", "nl": "nl",
    "pl": "pl", "hi": "hi", "ms": "ms", "auto": "auto",
}

LANG_NAME = {
    "zh-Hans": "简体中文", "zh-Hant": "繁體中文", "en": "English", "ja": "日本語",
    "ko": "한국어", "fr": "Français", "de": "Deutsch", "es": "Español",
    "ru": "Русский", "pt": "Português", "it": "Italiano", "th": "ไทย", "vi": "Tiếng Việt",
}


def norm_lang(code: str) -> str:
    c = (code or "").strip().lower()
    return LANG_ALIAS.get(c, c or "auto")


class Translator:
    name = "base"

    def translate(self, text: str, src: str, tgt: str, context: Optional[list[str]] = None) -> str:
        raise NotImplementedError

    def available(self) -> tuple[bool, str]:
        return True, ""


# --------------------------------------------------------------------------
# 免费 Bing 网页接口
# --------------------------------------------------------------------------
class BingTranslator(Translator):
    name = "bing"

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

    def __init__(self, host: str = "https://cn.bing.com"):
        self.host = host.rstrip("/")
        self._lock = threading.Lock()
        self._sess: Optional[requests.Session] = None
        self._token = ""
        self._key = ""
        self._ig = ""
        self._iid = "translator.5028"
        self._ts = 0.0

    def _ensure(self, force: bool = False) -> None:
        with self._lock:
            if self._sess is not None and not force and time.time() - self._ts < 540:
                return
            s = requests.Session()
            s.headers.update({
                "User-Agent": self.UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
            r = s.get(self.host + "/translator", timeout=12)
            r.raise_for_status()
            m = re.search(r'params_AbusePreventionHelper\s*=\s*\[([0-9]+),"([^"]+)"', r.text)
            if not m:
                raise RuntimeError("无法从 bing 页面获取翻译 token")
            ig = re.search(r'IG:"([^"]+)"', r.text)
            iid = re.search(r'data-iid="([^"]+)"', r.text)
            self._sess = s
            self._key, self._token = m.group(1), m.group(2)
            self._ig = ig.group(1) if ig else ""
            self._iid = iid.group(1) if iid else "translator.5028"
            self._ts = time.time()

    def translate(self, text: str, src: str, tgt: str, context: Optional[list[str]] = None) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        from_lang = norm_lang(src) if norm_lang(src) != "auto" else "auto-detect"
        to_lang = norm_lang(tgt)
        same = from_lang.split("-")[0] == to_lang.split("-")[0]
        for attempt in range(4):
            try:
                self._ensure(force=attempt > 0)
                out = self._post(text, from_lang, to_lang)
                # bing 首次请求常"原样返回"，视为失败重试
                if out and (same or out.strip() != text):
                    return out
            except Exception:
                pass
            time.sleep(0.15)
        return text

    def _post(self, text: str, from_lang: str, to_lang: str) -> str:
        url = (f"{self.host}/ttranslatev3?isVertical=1&&IG={self._ig}"
               f"&IID={self._iid.replace('.5028', f'.{int(time.time()*1000) % 9000 + 1000}')}")
        s = self._sess
        assert s is not None
        data = {"fromLang": from_lang, "text": text, "to": to_lang,
                "token": self._token, "key": self._key}
        r = s.post(url, data=data, timeout=12, headers={
            "Origin": self.host, "Referer": self.host + "/translator",
            "Content-Type": "application/x-www-form-urlencoded"})
        if r.status_code == 401:
            raise RuntimeError("token expired")
        r.raise_for_status()
        js = r.json()
        if isinstance(js, list) and js:
            return js[0]["translations"][0]["text"]
        if isinstance(js, dict) and "translations" in js:
            return js["translations"][0]["text"]
        return ""

    def warmup(self) -> None:
        """预热：bing 首次 POST 常失败，先打一发。"""
        try:
            self._ensure()
            self.translate("Hello.", "en", "zh-Hans")
        except Exception:
            pass


# --------------------------------------------------------------------------
# LLM 翻译（DeepSeek / OpenAI 兼容）
# --------------------------------------------------------------------------
SYS_TMPL = (
    "你是专业的实时同传翻译引擎。把用户输入从{src}翻译成{tgt}。"
    "要求：只输出译文本身，不要解释、不要引号、不要加前后缀；"
    "保持口语自然、简洁，与原句长度相近；保留人名、数字、专有名词；"
    "如果输入是不完整的半句话，就按现有内容直译，不要补全、不要编造。"
)


class LLMTranslator(Translator):
    name = "llm"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "未配置 API Key"
        return True, ""

    def translate(self, text: str, src: str, tgt: str, context: Optional[list[str]] = None) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        s_lang = LANG_NAME.get(norm_lang(src), norm_lang(src) if norm_lang(src) != "auto" else "原文语言")
        t_lang = LANG_NAME.get(norm_lang(tgt), norm_lang(tgt))
        messages = [{"role": "system", "content": SYS_TMPL.format(src=s_lang, tgt=t_lang)}]
        if context:
            ctx = "\n".join(f"- {c}" for c in context[-3:] if c)
            messages.append({"role": "user", "content": f"【上文参考】\n{ctx}"})
            messages.append({"role": "assistant", "content": "好的，我会保持上下文连贯。"})
        messages.append({"role": "user", "content": text})
        payload = {"model": self.model, "messages": messages, "temperature": 0.2,
                   "max_tokens": 512, "stream": False}
        r = requests.post(self.base_url + "/chat/completions",
                          headers={"Authorization": f"Bearer {self.api_key}",
                                   "Content-Type": "application/json"},
                          json=payload, timeout=self.timeout)
        r.raise_for_status()
        js = r.json()
        out = js["choices"][0]["message"]["content"].strip()
        return out.strip().strip('"“”')


class DeepSeekTranslator(LLMTranslator):
    name = "deepseek"


# --------------------------------------------------------------------------
# 本地 NLLB（ctranslate2）
# --------------------------------------------------------------------------
NLLB_CODES = {"zh-Hans": "zho_Hans", "zh-Hant": "zho_Hant", "en": "eng_Latn", "ja": "jpn_Jpan",
              "ko": "kor_Hang", "fr": "fra_Latn", "de": "deu_Latn", "es": "spa_Latn",
              "ru": "rus_Cyrl", "pt": "por_Latn", "it": "ita_Latn", "ar": "arb_Arab",
              "th": "tha_Thai", "vi": "vie_Latn", "id": "ind_Latn", "tr": "tur_Latn"}


_CJK = r"\u4e00-\u9fff"


def _tidy_mt(text: str) -> str:
    """整理译文：去掉中文之间的空格、补句末标点、压缩多余空白。"""
    s = (text or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    s = re.sub(rf"(?<=[{_CJK}]) (?=[{_CJK}])", "", s)
    s = re.sub(rf"(?<=[{_CJK}]) (?=[，。！？；：、])", "", s)
    s = re.sub(rf"(?<=[，。！？；：、]) (?=[{_CJK}])", "", s)
    s = re.sub(r"\s+([,.!?;:])", r"\1", s)
    return s.strip()


class OpusMtTranslator(Translator):
    """离线翻译：Helsinki opus-mt（CTranslate2 int8），英中双向各一个模型。

    目录结构（models/mt/）：
        opus-en-zh/{model.bin,source.spm,target.spm}
        opus-zh-en/{model.bin,source.spm,target.spm}

    纯 CPU、不依赖 torch；单句约 0.1–0.3 秒，内存约 150 MB。
    """

    name = "opus"

    def __init__(self, base_dir: Path, threads: int = 4, beam_size: int = 4):
        self.base = Path(base_dir)
        self.threads = max(1, int(threads))
        self.beam_size = max(1, int(beam_size))
        self._eng: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        for sub in ("opus-en-zh", "opus-zh-en"):
            if not (self.base / sub / "model.bin").exists():
                return False, f"本地翻译模型不存在：{self.base / sub}"
        return True, ""

    def _dirs(self, src: str, tgt: str) -> str:
        s, t = norm_lang(src), norm_lang(tgt)
        if t.startswith("zh") and not s.startswith("zh"):
            return "opus-en-zh"
        if s.startswith("zh") and not t.startswith("zh"):
            return "opus-zh-en"
        # 其他语种先按 en→zh 兜底（opus-mt 只做中英）
        return "opus-en-zh"

    def _load(self, sub: str):
        with self._lock:
            if sub in self._eng:
                return self._eng[sub]
            import ctranslate2
            import sentencepiece

            d = self.base / sub
            eng = ctranslate2.Translator(str(d), device="cpu", compute_type="int8",
                                         intra_threads=self.threads, inter_threads=1)
            src_sp = sentencepiece.SentencePieceProcessor(str(d / "source.spm"))
            tgt_sp = sentencepiece.SentencePieceProcessor(str(d / "target.spm"))
            self._eng[sub] = (eng, src_sp, tgt_sp)
            return self._eng[sub]

    def translate(self, text: str, src: str, tgt: str,
                  context: Optional[list[str]] = None) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        sub = self._dirs(src, tgt)
        eng, src_sp, tgt_sp = self._load(sub)
        # Marian 的编码器输入必须以 </s> 结尾（HF tokenizer 会自动加），
        # 少了它模型会退化成逐词重复的乱码。
        tokens = src_sp.encode(text, out_type=str) + ["</s>"]
        res = eng.translate_batch([tokens], beam_size=self.beam_size,
                                  max_batch_size=1, max_decoding_length=256)
        out = res[0].hypotheses[0]
        text_out = tgt_sp.decode([t for t in out if t not in ("</s>", "<pad>")]).strip()
        return _tidy_mt(text_out)

    def warmup(self) -> None:
        try:
            self.translate("Hello, nice to meet you.", "en", "zh-Hans")
            self.translate("你好，很高兴认识你。", "zh", "en")
        except Exception:
            pass


class NllbTranslator(Translator):
    name = "nllb"

    def __init__(self, model_dir: Path, threads: int = 4):
        self.dir = Path(model_dir)
        self.threads = max(1, int(threads))
        self._engine = None
        self._sp = None
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        if not (self.dir / "model.bin").exists():
            return False, f"本地模型不存在：{self.dir}"
        return True, ""

    def _load(self):
        with self._lock:
            if self._engine is not None:
                return
            import ctranslate2
            self._engine = ctranslate2.Translator(str(self.dir), device="cpu",
                                                  compute_type="int8", inter_threads=1,
                                                  intra_threads=self.threads)
            import sentencepiece
            self._sp = sentencepiece.SentencePieceProcessor(str(self.dir / "sentencepiece.bpe.model"))

    def translate(self, text: str, src: str, tgt: str, context: Optional[list[str]] = None) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        self._load()
        s = NLLB_CODES.get(norm_lang(src), "eng_Latn")
        t = NLLB_CODES.get(norm_lang(tgt), "zho_Hans")
        tokens = self._sp.encode(text, out_type=str)
        res = self._engine.translate_batch([[s] + tokens], target_prefix=[[t]], beam_size=2,
                                           max_batch_size=1, max_decoding_length=256)
        out = res[0].hypotheses[0]
        if out and out[0] == t:
            out = out[1:]
        return self._sp.decode(out)


class Passthrough(Translator):
    name = "none"

    def translate(self, text: str, src: str, tgt: str, context: Optional[list[str]] = None) -> str:
        return text


# --------------------------------------------------------------------------
def build_translator(cfg) -> Translator:
    eng = (cfg.mt_engine or "bing").lower()
    if getattr(cfg, "offline_only", False) and eng not in ("none", "opus", "opus-mt", "local", "nllb"):
        # 离线模式：优先用质量更好的本地模型，没有就退回 opus-mt 极速版
        nllb_dir = Path(getattr(cfg, "nllb_dir", "") or
                        (Path(__file__).resolve().parent.parent.parent / "models" / "mt" /
                         "nllb-600m-int8"))
        eng = "nllb" if (nllb_dir / "model.bin").exists() else "opus"
    if eng == "deepseek":
        return DeepSeekTranslator(cfg.deepseek_base, cfg.deepseek_api_key, cfg.deepseek_model)
    if eng == "openai":
        return LLMTranslator(cfg.deepseek_base, cfg.deepseek_api_key, cfg.deepseek_model)
    if eng in ("opus", "opus-mt", "local"):
        base = Path(getattr(cfg, "opus_dir", "") or (Path(__file__).resolve().parent.parent.parent
                                                    / "models" / "mt"))
        return OpusMtTranslator(base, threads=getattr(cfg, "mt_threads", 4))
    if eng == "nllb":
        d = getattr(cfg, "nllb_dir", "")
        base = Path(d) if d else (Path(__file__).resolve().parent.parent.parent
                                  / "models" / "mt" / "nllb-600m-int8")
        return NllbTranslator(base, threads=getattr(cfg, "mt_threads", 4))
    if eng == "none":
        return Passthrough()
    return BingTranslator()
