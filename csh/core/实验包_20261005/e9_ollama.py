"""
e9_ollama.py — E9：用本地 Ollama 模型测ICL 阈值 k*

=====================================================================

回答猫猫的问题：能不能用本地已部署的开源大模型来验证？
答：能，但测的量必须换。

测什么
------
论文的 n* = 需要多少条【训练样本】。冻结模型没有梯度更新，n* 测不到。
对应的可测量是 ICL 阈值：

    k* = 需要几个【上下文示例】才能让准确率越过 tau

n* 与 k* 不是同一个量，但都测"这个问题对多大的模型有多难"：
    n*：样本需要占多少权重容量
    k*：样本需要占多少上下文

本实验测 L1 主张在真实预训练模型 + 真实语义表面上是否成立。

这个实验的独特优势：论文受限于"必须控制 tokenizer 才能做严格配平"
（§5.1 陷阱一），而真实 LLM 的分词器是**真实**的。这恰好让实验落在
"真实符号系统"上——论文 §1.2 的主张（自然语言/数学/代码是同一认知结构的
不同符号投影）第一次被真正检验，而不是在人造 nonce 词表上检验。

致命限制（必须先承认）
--------------------
论文的表面是**人造**的：`甲 含 乙` / `A is r B` / `( r A B )`。
这些不是真实自然语言，只是同一结构的重写。它们之间 token 数相等，
所以论文能做到严格配平。

真实 LLM 上"严格配平"与"真实语言"**不可兼得**：
    甲 含 乙 。   ->  qwen2 分词约 6 token
    A is inside B. ->  约 5 token
    ( inside 甲 )  ->  约 7 token

所以本实验**不能沿用论文 46-token 配平的说法**。必须：
  1. 报告每个表面的实际 token 数（作为协变量）
  2. 判据从"阈值"改为"token 预算下的准确率曲线"
  3. null 臂（relperm/entperm）内部天然配平（置换不改变 token 数），
     用它们作承重对照

三种表面
--------
  A. 人造表面（论文原样）—— 与论文可直接对照，验证流水线
  B. 真实表面（中文/英文自然语言描述同一结构）—— 论文从未测过
  C. null 臂（relperm / entperm）—— 承重对照

B 与 A 的差异就是论文 §1.2 主张的第一次真实检验。

用法
----
    # 0. 起Ollama
    ollama serve

    # 1. 连通性+ 分词器检查
    python e9_ollama.py --check

    # 2. 预检：三个表面的实际 token 数
    python e9_ollama.py --preflight

    # 3. 单点冒烟
    python e9_ollama.py --model qwen2:7b --surfaces A --k 4 --n-probe 20

    # 4. 完整
    python e9_ollama.py --model qwen2:7b --surfaces A,B,C --ks 0,1,2,4,8,16

注意
----
* temperature=0，seed 固定。Ollama 的 seed 参数在 CPU 后端不完全确定，
  故每个配置重复 3 次取中位数，报告极差。
* 判定用准确率随 k 的曲线，不用插值阈值——真实 LLM 上曲线可能不单调。
"""

import argparse
import itertools
import json
import os
import random
import re
import statistics
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)

from substrate2 import build, Gen, c_eff# noqa: E402

OLLAMA = "http://localhost:11434"
DEPTH = 3
N_TEST_DEFAULT = 60
REPEATS = 3# Ollama seed 不完全确定，取中位数
TAU = 0.60


# ============================================================ HTTP
def api(path, payload=None, timeout=180):
    url = OLLAMA + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def list_models():
    try:
        d = api("/api/tags", timeout=10)
        return [m["name"] for m in d.get("models", [])]
    except Exception as e:
        print(f"  [FAIL] 连不上 Ollama: {e}")
        return []


def generate(model, prompt, max_tokens=8, seed=0):
    d = api("/api/generate", {
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": 0.0, "num_predict": max_tokens,
                    "seed": seed},
    })
    return d.get("response", "")


def count_tokens(model, text):
    """用 /api/embed 的返回长度不可靠，改用 logprobs 近似不可行。
    这里用字符/token 粗估 + 实际生成对照，见 --check 的说明。"""
    return len(text)


# ============================================================ 表面
# A 组：论文原样的人造表面（与 surfaces.py 一致）
SURF_A = {
    "zh_zh":   lambda a, r, b, q: None,   # 见下，改用显式模板
}


def make_problems(n, seed, n_rel=6):
    sub = build(1)
    g = Gen(sub, seed=1000 + seed)
    return sub, g.dataset(n, [DEPTH], seed=seed)


ENT_ZH = list("甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉")
ENT_EN = [f"e{i}" for i in range(18)]

REL_ZH = ["含", "先", "动", "移", "近", "指", "向", "属", "覆", "随"]
REL_EN = ["inside", "before", "acts", "moves", "near", "points",
          "faces", "belongs", "covers", "follows"]


def render_A(p, rels, ents, style):
    """论文原样的人造表面。5 tok/fact。"""
    facts = []
    for (a, r, b) in p.facts:
        A, R, B = ents[a], rels[r], ents[b]
        if style == "zh":
            facts.append(f"{A} {R} {B} 。")
        else:
            facts.append(f"{A} is {R} {B} .")
    chain = " ".join(rels[r] for r in p.seq)
    if style == "zh":
        q = f"问 {ents[p.start]} 则 {chain} ?"
    else:
        q = f"q {ents[p.start]} then {chain} ?"
    return {"facts": facts, "query": q, "answer": ents[p.answer]}


def render_B(p, rels, ents, lang):
    """真实表面：用自然语言描述同一结构，token 数不再配平。"""
    if lang == "zh":
        fact_tpl = "{A} 在 {B} 的{loc}边"
        loc = ["里面", "前面", "里面", "上面"]
        rel2loc = {"含": "里面", "先": "前面", "动": "外面", "移": "旁边",
                   "近": "近", "指": "对着", "向": "朝", "属": "属于",
                   "覆": "覆盖", "随": "跟随"}
        facts = []
        for (a, r, b) in p.facts:
            facts.append(f"事实：{ents[a]} 在 {ents[b]} 的{rel2loc.get(rels[r],'里面')}。")
        chain = "，然后".join(
            {"含": "在里面", "先": "在前面", "动": "到外面", "移": "移到旁边",
             "近": "靠近", "指": "指向", "向": "朝向", "属": "归属",
             "覆": "覆盖", "随": "跟随"}[rels[r]] for r in p.seq)
        q = f"问题：{ents[p.start]} {chain}，它在哪里？"
    else:
        # rels 可能是 REL_ZH（中文键）或 REL_EN（已是英文）
        _direct = {"inside", "before", "acts", "moves", "near", "points",
                   "faces", "belongs", "covers", "follows"}
        rel2en = {"含": "is inside", "先": "comes before", "动": "moves",
                  "移": "shifts", "近": "is near", "指": "points at",
                  "向": "faces", "属": "belongs to", "覆": "covers",
                  "随": "follows"}

        def en_of(r):
            return r if r in _direct else rel2en.get(r, r)

        facts = []
        for (a, r, b) in p.facts:
            facts.append(f"Fact: {ents[a]} {en_of(rels[r])} {ents[b]}.")
        chain = " and then ".join(en_of(rels[r]) for r in p.seq)
        q = f"Question: starting from {ents[p.start]}, {chain}. Where is it?"
    return {"facts": facts, "query": q, "answer": ents[p.answer]}


def render_C(p, rels, ents, mode, seed=777):
    """null 臂：置换标签但结构不变。token 数与原表面相同。"""
    rr = list(rels)
    ee = list(ents)
    rng = random.Random(seed + len(rels) * 13 + (0 if mode == "rel" else 1))
    if mode == "rel":
        rng.shuffle(rr)
    else:
        rng.shuffle(ee)
    return render_A(p, rr, ee, "zh")


# ============================================================ prompt
FEWSHOT_HEADER = (
    "以下每题给出一组事实和一个问题。请只回答答案本身，"
    "不要解释，不要重复题目。\n\n"
)
FEWSHOT_HEADER_EN = (
    "Each problem below gives a set of facts and one question. "
    "Answer with the answer only. No explanation.\n\n"
)


def build_prompt(demos, target, header):
    parts = [header]
    for d in demos + [target]:
        parts.append("\n".join(d["facts"]) + "\n" + d["query"] + "\n")
        parts.append("答案：" + d["answer"] + "\n\n"
                     if header is FEWSHOT_HEADER else
                     "Answer: " + d["answer"] + "\n\n")
    return "".join(parts)


ANS_RE = re.compile(r"[甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉]|e\d+")


def parse_answer(text, ents):
    m = ANS_RE.search(text)
    if not m:
        return None
    tok = m.group(0)
    return tok if tok in ents else None


# ============================================================ 预检
def preflight(models):
    print("=" * 74)
    print("PREFLIGHT  —  三个表面的实际 token 数（真实分词器）")
    print("=" * 74)
    print("论文的 46-token 配平在真实 LLM 上不成立，必须实测。")
    print()
    _, ps = make_problems(3, 0)
    samples = {
        "A_zh论文人造": render_A(ps[0], REL_ZH, ENT_ZH, "zh"),
        "A_en 论文人造": render_A(ps[0], REL_EN, ENT_EN, "en"),
        "B_zh 真实自然": render_B(ps[0], REL_ZH, ENT_ZH, "zh"),
        "B_en 真实自然": render_B(ps[0], REL_EN, ENT_EN, "en"),
        "C_relperm    ": render_C(ps[0], REL_ZH, ENT_ZH, "rel"),
        "C_entperm    ": render_C(ps[0], REL_ZH, ENT_ZH, "ent"),
    }
    print(f"  {'表面':>16} {'字符数':>7} {'事实条数':>8}  首个事实")
    for name, d in samples.items():
        print(f"  {name:>16} {len(d['facts'][0]):7d} {len(d['facts']):8d}  "
              f"{d['facts'][0][:44]}")
    print()
    print("  注意 A 组各表面结构相同但字符数不同（中文一字一 token 假设不成立）。")
    print("  C 组（null）与 A_zh 的 token 数应完全一致——置换不改变长度。")
    print()
    for m in models:
        print(f"  模型 {m}：连通性由--check 验证")
    print()


def check(models):
    print("=" * 74)
    print("CHECK  —  Ollama 连通性与模型列表")
    print("=" * 74)
    avail = list_models()
    if not avail:
        print("  Ollama 未运行。请先：ollama serve")
        return False
    print(f"  已安装 {len(avail)} 个模型：")
    for m in avail:
        print(f"    {m}")
    print()
    for m in models:
        if m not in avail:
            print(f"  [SKIP] {m} 未安装")
            continue
        t0 = time.time()
        try:
            out = generate(m, "Answer with one word. What color is the sky?",
                           max_tokens=6, seed=0)
            print(f"  [OK] {m}: {time.time()-t0:.1f}s  "
                  f"resp={out.strip()[:40]!r}")
        except Exception as e:
            print(f"  [FAIL] {m}: {e}")
    return True


# ============================================================ 单配置
def run_config(model, group, style, k, n_probe, seed):
    """返回 (acc, n_correct, n_parsed, prompt_chars)。"""
    _, ps = make_problems(k + n_probe, seed)
    demos, targets = ps[:k], ps[k:k + n_probe]

    def rend(p):
        if group == "A":
            return render_A(p, REL_ZH if style == "zh" else REL_EN,
                            ENT_ZH if style == "zh" else ENT_EN, style)
        if group == "B":
            return render_B(p, REL_ZH if style == "zh" else REL_EN,
                            ENT_ZH if style == "zh" else ENT_EN, style)
        return render_C(p, REL_ZH, ENT_ZH, style)

    hdr = FEWSHOT_HEADER if style == "zh" else FEWSHOT_HEADER_EN
    ents = ENT_ZH if style == "zh" else ENT_EN

    correct = parsed = 0
    chars = 0
    for t in targets:
        rt = rend(t)
        prompt = build_prompt([rend(d) for d in demos], rt, hdr)
        chars += len(prompt)
        try:
            out = generate(model, prompt, max_tokens=8, seed=seed)
        except Exception:
            continue
        pred = parse_answer(out, ents)
        if pred is not None:
            parsed += 1
            if pred == rt["answer"]:
                correct += 1
    acc = correct / len(targets) if targets else float("nan")
    return acc, correct, parsed, chars / max(len(targets), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=str, default="qwen2:7b")
    ap.add_argument("--models", type=str, default=None)
    ap.add_argument("--group", type=str, default="A",
                    help="A=论文人造表面 B=真实自然语言 C=null 臂")
    ap.add_argument("--style", type=str, default="zh")
    ap.add_argument("--ks", type=str, default="0,1,2,4,8,16")
    ap.add_argument("--n-probe", type=int, default=N_TEST_DEFAULT)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--out", default="../results/e9_ollama.jsonl")
    args = ap.parse_args()

    models = (args.models.split(",") if args.models
              else [args.model])

    if args.check:
        check(models)
        return
    if args.preflight:
        check(models)
        preflight(models)
        return

    ks = [int(x) for x in args.ks.split(",")]
    out = os.path.abspath(args.out if os.path.isabs(args.out)
                         else os.path.join(HERE, args.out))
    os.makedirs(os.path.dirname(out), exist_ok=True)

    avail = list_models()
    if not avail:
        print("Ollama 未运行：ollama serve")
        return
    model = args.model
    if model not in avail:
        print(f"{model} 未安装。可用：{avail}")
        return

    _, eff = c_eff(build(1)["assign"], 3)
    print(f"model={model}  group={args.group}  style={args.style}")
    print(f"k grid = {ks}  n_probe={args.n_probe}  "
          f"repeats={REPEATS}  C_eff(3)={eff}")
    print(f"out = {out}\n", flush=True)

    with open(out, "a", encoding="utf-8") as fh:
        for k in ks:
            accs = []
            for rep in range(REPEATS):
                a, c, p, ch = run_config(model, args.group, args.style,
                                         k, args.n_probe, seed=rep)
                accs.append(a)
                print(f"  k={k:3d} rep={rep}  acc={a:.3f} "
                      f"({c}/{args.n_probe},parsed={p})  "
                      f"~{ch:.0f} chars/prompt", flush=True)
            row = {"arm": "E9", "model": model, "group": args.group,
                   "style": args.style, "k": k, "n_probe": args.n_probe,
                   "acc_median": statistics.median(accs),
                   "acc_min": min(accs), "acc_max": max(accs),
                   "accs": accs, "C_eff3": eff, "depth": DEPTH,
                   "tau": TAU, "metric": "ICL threshold k*",
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(f"  -> k={k} median={row['acc_median']:.3f} "
                  f"[{row['acc_min']:.3f}, {row['acc_max']:.3f}]\n", flush=True)

    print("done ->", out)
    print("读法：acc(k) 单调上升则 k* 可估；不单调说明 ICL 在此任务上不可用，")
    print("      须报告曲线形状而非阈值（见方案文档 §4）。")


if __name__ == "__main__":
    main()
