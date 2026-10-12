# -*- coding: utf-8 -*-
"""VERIFY prompt-arm ceiling eval. Runs on PC. Never prints API keys."""
import bisect, json, os, re, sys, time, urllib.request, statistics, random
from pathlib import Path

BASE = None
for dp, dns, fns in os.walk(r"%DSH_ROOT%\lir"):
    if "runtime" in dp or "site-packages" in dp:
        continue
    if os.path.basename(dp).startswith("dsh-") and "v3" in dns and any(x.startswith("corpus") for x in dns):
        logs = os.path.join(dp, "v3", "logs")
        sj = os.path.join(logs, "samples.jsonl")
        if os.path.isfile(sj) and os.path.getsize(sj) > 400000:
            BASE = dp
            break
assert BASE, "cowrite base not found"
V3 = os.path.join(BASE, "v3")
sys.path.insert(0, V3)
import classifier as C
from classifier import classify, load_params, is_en

CFG_CANDIDATES = [
    os.path.join(BASE, "config.json"),
    r"%DSH_ROOT%\cowrite-dist\Cowrite-test\app\config.json",
]
cfg = None
CFG_PATH = None
for p in CFG_CANDIDATES:
    if os.path.isfile(p):
        cfg = json.load(open(p, encoding="utf-8"))
        CFG_PATH = p
        break
assert cfg and cfg.get("api_key"), "no config"

OUT = Path(os.environ.get("COWRITE_VERIFY_OUT", "verify_results"))
OUT.mkdir(exist_ok=True)

params = load_params()
random.seed(20261012)


def find_corpus(exact=None, pred=None):
    for name in os.listdir(BASE):
        p = os.path.join(BASE, name)
        if not os.path.isdir(p):
            continue
        if exact and name == exact:
            return p
        if pred and pred(name, p):
            return p
    return None


CORP_S = find_corpus(exact="corpus_S")
CORP_GENRE = None
CORP_PRIV = None
for name in os.listdir(BASE):
    p = os.path.join(BASE, name)
    if not os.path.isdir(p) or not name.startswith("corpus_"):
        continue
    if name == "corpus_S":
        continue
    nmd = len([f for f in os.listdir(p) if f.endswith(".md")])
    if "私" in name:
        CORP_PRIV = p
    elif 5 <= nmd <= 15 and "非P" not in name and "合成" not in name:
        CORP_GENRE = p

print("BASE", BASE)
print("CORP_S", CORP_S)
print("CORP_GENRE", CORP_GENRE)
print("CORP_PRIV", CORP_PRIV)
print("CFG", CFG_PATH)
print("model", cfg.get("model"), "provider", cfg.get("provider"))


def load_paras(d, per_file=80, total=800, min_chars=40, lang=None):
    out = []
    if not d or not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        t = open(os.path.join(d, fn), encoding="utf-8").read()
        ps = [
            x.strip()
            for x in re.split(r"\n\s*\n", t)
            if x.strip() and not x.startswith(("#", ">")) and len(x.strip()) >= min_chars
        ]
        kept = []
        for p in ps:
            en = is_en(p)
            if lang == "zh" and en:
                continue
            if lang == "en" and not en:
                continue
            kept.append(p)
        if len(kept) > per_file:
            step = len(kept) / per_file
            kept = [kept[int((i + 0.5) * step)] for i in range(per_file)]
        out.extend(kept)
        if len(out) >= total:
            break
    return out[:total]


def auc(pos, neg):
    neg = sorted(neg)
    s = 0.0
    for p in pos:
        lo = bisect.bisect_left(neg, p)
        hi = bisect.bisect_right(neg, p)
        s += lo + 0.5 * (hi - lo)
    return s / max(1, len(pos) * len(neg))


feat_report = {
    "feature_impl": "v3/classifier.py + params.json classifier.weights",
    "params_version": params.get("version"),
}

A_s = load_paras(CORP_S, per_file=120, total=1200, min_chars=40)
B_g = load_paras(CORP_GENRE, per_file=150, total=1200, min_chars=40)
print("loaded S", len(A_s), "genre", len(B_g))


def scores(texts):
    sc = []
    for t in texts:
        _, score, _ = classify(t, params)
        sc.append(score)
    return sc


sc_s = scores(A_s)
sc_g = scores(B_g)
auc_cross = auc(sc_s, sc_g) if sc_s and sc_g else None
auc_cross_rev = auc(sc_g, sc_s) if sc_s and sc_g else None
feat_report["cross_lang"] = {
    "n_S": len(sc_s),
    "n_genre": len(sc_g),
    "mean_S": round(statistics.mean(sc_s), 4) if sc_s else None,
    "mean_genre": round(statistics.mean(sc_g), 4) if sc_g else None,
    "AUC_S_vs_genre": round(auc_cross, 4) if auc_cross is not None else None,
    "AUC_genre_vs_S": round(auc_cross_rev, 4) if auc_cross_rev is not None else None,
    "note": "lexical feature mode_score; near 0.5 = inseparable",
}

zh_novel, zh_prose = [], []
if CORP_PRIV:
    for fn in sorted(os.listdir(CORP_PRIV)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(CORP_PRIV, fn)
        t = open(path, encoding="utf-8").read()
        ps = [
            x.strip()
            for x in re.split(r"\n\s*\n", t)
            if x.strip()
            and not x.startswith(("#", ">"))
            and len(x.strip()) >= 40
            and not is_en(x)
        ]
        if len(ps) > 200:
            step = len(ps) / 200
            ps = [ps[int((i + 0.5) * step)] for i in range(200)]
        if any(k in fn for k in ["格非", "杀夫", "生命", "银闪"]):
            zh_novel.extend(ps)
        elif any(k in fn for k in ["水问", "简", "白", "晚餐", "结"]):
            zh_prose.extend(ps)

sc_n = scores(zh_novel)
sc_p = scores(zh_prose)
auc_zh = auc(sc_n, sc_p) if sc_n and sc_p else None
auc_zh_rev = auc(sc_p, sc_n) if sc_n and sc_p else None
feat_report["same_lang_zh"] = {
    "n_novel": len(sc_n),
    "n_prose": len(sc_p),
    "mean_novel": round(statistics.mean(sc_n), 4) if sc_n else None,
    "mean_prose": round(statistics.mean(sc_p), 4) if sc_p else None,
    "AUC_novel_vs_prose": round(auc_zh, 4) if auc_zh is not None else None,
    "AUC_prose_vs_novel": round(auc_zh_rev, 4) if auc_zh_rev is not None else None,
    "note": "file-name heuristic split inside corpus_private; aligns with paper same-lang setup",
}

json.dump(
    feat_report,
    open(OUT / "feature_offline.json", "w", encoding="utf-8"),
    ensure_ascii=False,
    indent=2,
)
print("FEATURE", json.dumps(feat_report, ensure_ascii=False, indent=2))

HOLD_N = 30


def sample_holdout(texts, n):
    if len(texts) <= n:
        return list(texts)
    idx = list(range(len(texts)))
    random.shuffle(idx)
    return [texts[i] for i in idx[:n]]


hold_pos = sample_holdout(A_s, HOLD_N)
hold_neg = sample_holdout(B_g, HOLD_N)
hold = [("S", t) for t in hold_pos] + [("P", t) for t in hold_neg]
random.shuffle(hold)

import policy as P

def arm_A_system():
    return (
        "你是文本分类器。根据给定段落，判断它更接近：\n"
        "P=问题驱动/意识流（张力悬置、重复变奏、弱因果）\n"
        "M=混合\n"
        "S=故事驱动（目标、因果、时间线）\n"
        '只输出一行 JSON：{"mode":"P|M|S","score":0到1的小数}。\n'
        "score 越大越偏 S。不要解释。"
    )


def arm_B_system(sample_text):
    system, meta = P.build_system(sample_text, params)
    extra = (
        "\n\n---\n【本回合额外任务·VERIFY】忽略伴写输出形态。"
        "只根据上面的模式定义与铁律语境，对【用户给出的段落】判定 P/M/S。"
        '只输出一行 JSON：{"mode":"P|M|S","score":0到1的小数}（越大越偏 S）。不要伴写正文。'
    )
    return system + extra, meta


def arm_C_system(sample_text):
    system, meta = arm_B_system(sample_text)
    civ = (
        "\n\n【文明条款 C1–C13 与注意力工作流（全文框架）】\n"
        "- 注意力：仅在段末/停顿阈值后出声；CODING 沉默；一次一个动作；⊘ 是合法输出。\n"
        "- 文明：不指点、不评价、不探问作者状态、不中英混杂、不列方案清单。\n"
        "这些框架改变你如何读文本；仍只输出 mode/score JSON，不输出伴写。\n"
    )
    return system + civ, meta


MODE_TO_SCORE = {"P": 0.15, "M": 0.5, "S": 0.85}


def call_model(system, user, temperature=0.3):
    payload = {
        "model": cfg.get("model"),
        "messages": [{"role": "user", "content": user}],
        "system": system,
        "max_tokens": 64,
        "temperature": float(temperature),
        "thinking": {"type": "disabled"},
    }
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": cfg.get("api_key", ""),
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    txt = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return txt.strip()


def parse_pred(txt):
    m = re.search(r"\{[^}]+\}", txt)
    mode, score = None, None
    if m:
        try:
            d = json.loads(m.group(0))
            mode = str(d.get("mode", "")).upper().strip()
            score = d.get("score")
            if isinstance(score, str):
                score = float(score)
        except Exception:
            pass
    if mode not in ("P", "M", "S"):
        mm = re.search(r"\b([PMS])\b", txt)
        mode = mm.group(1) if mm else None
    if score is None and mode:
        score = MODE_TO_SCORE.get(mode)
    try:
        score = float(score) if score is not None else None
    except Exception:
        score = MODE_TO_SCORE.get(mode) if mode else None
    return mode, score, txt[:120]


def run_arm(arm_name, make_system, items):
    rows = []
    for i, (lab, text) in enumerate(items):
        if arm_name == "A":
            system = make_system()
        else:
            system, _meta = make_system(text)
        user = "段落：\n" + text[:1200]
        try:
            raw = call_model(system, user, temperature=0.3)
            mode, score, prev = parse_pred(raw)
            err = None
        except Exception as e:
            mode, score, prev, err = None, None, "", "%s: %s" % (type(e).__name__, str(e)[:160])
        rows.append(
            {
                "i": i,
                "label": lab,
                "y": 1 if lab == "S" else 0,
                "pred_mode": mode,
                "score": score,
                "preview": prev,
                "error": err,
                "text_chars": len(text),
            }
        )
        print(arm_name, i + 1, "/", len(items), lab, mode, score, err or "ok")
        time.sleep(0.15)
    return rows


def summarize(rows):
    ok = [r for r in rows if r["score"] is not None]
    pos = [r["score"] for r in ok if r["y"] == 1]
    neg = [r["score"] for r in ok if r["y"] == 0]
    a = auc(pos, neg) if pos and neg else None
    correct = sum(1 for r in ok if r["pred_mode"] == r["label"])
    acc = correct / max(1, len(ok))
    return {
        "n_total": len(rows),
        "n_scored": len(ok),
        "n_errors": sum(1 for r in rows if r["error"]),
        "AUC": round(a, 4) if a is not None else None,
        "Acc_mode_exact": round(acc, 4),
        "mean_score_S": round(statistics.mean(pos), 4) if pos else None,
        "mean_score_P": round(statistics.mean(neg), 4) if neg else None,
        "class_prior_S": round(sum(1 for r in rows if r["y"] == 1) / len(rows), 4),
    }


print("HOLD", len(hold), "pos", sum(1 for l, _ in hold if l == "S"), "neg", sum(1 for l, _ in hold if l == "P"))

results = {}
rows_a = run_arm("A", arm_A_system, hold)
results["A"] = {"summary": summarize(rows_a), "rows": rows_a}
json.dump(results, open(OUT / "arm_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

rows_b = run_arm("B", arm_B_system, hold)
results["B"] = {"summary": summarize(rows_b), "rows": rows_b}
json.dump(results, open(OUT / "arm_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

rows_c = run_arm("C", arm_C_system, hold)
results["C"] = {"summary": summarize(rows_c), "rows": rows_c}

sa = (results["A"]["summary"] or {}).get("AUC")
sb = (results["B"]["summary"] or {}).get("AUC")
sc = (results["C"]["summary"] or {}).get("AUC")
d_ba = (sb - sa) if (sa is not None and sb is not None) else None
d_cb = (sc - sb) if (sb is not None and sc is not None) else None
stop_prereg = d_ba is not None and d_cb is not None and d_ba < 0.02 and d_cb < 0.02

meta = {
    "model": cfg.get("model"),
    "provider": cfg.get("provider"),
    "base_url_host": cfg.get("base_url", "").split("//")[-1].split("/")[0],
    "temperature": 0.3,
    "thinking": "disabled",
    "feature_impl": "v3/classifier.py + params.json",
    "params_version": params.get("version"),
    "label_set": "genre_proxy_P_vs_S (corpus_genre as P-proxy, corpus_S as S-proxy)",
    "label_batch": "holdout_n30_each_seed20261012",
    "delta_stop": "0.02 AUC x 2 consecutive steps",
    "arm_mapping": {
        "A": "approximate prompt-ablation: bare classifier instruction only (NOT runner baseline=SKILL+WORKFLOW)",
        "B": "policy.build_system (SKILL_v3 + mode/bans/iron) + classify-only suffix",
        "C": "B + civility C1-C13 + attention workflow text (NOT live cursor state machine)",
        "D": "not run (optional structure arm)",
        "native_unclean": "runner.py only has baseline|v3; attention is server-only; documented as approximate",
    },
    "deltas": {"B_minus_A": d_ba, "C_minus_B": d_cb},
    "STOP_prereg_signed_gain": stop_prereg,
    "STOP_note": "STOP if Delta(B-A) < 0.02 AND Delta(C-B) < 0.02",
}
out_obj = {
    "meta": meta,
    "table": {
        "A": results["A"]["summary"],
        "B": results["B"]["summary"],
        "C": results["C"]["summary"],
    },
    "feature": feat_report,
}
json.dump(out_obj, open(OUT / "arm_curve.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(results, open(OUT / "arm_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("DONE TABLE", json.dumps(out_obj["table"], ensure_ascii=False, indent=2))
print("DELTAS", meta["deltas"], "STOP", stop_prereg)
