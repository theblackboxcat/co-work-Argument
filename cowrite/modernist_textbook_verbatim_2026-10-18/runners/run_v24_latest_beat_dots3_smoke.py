# -*- coding: utf-8 -*-
"""SYSTEM_latest v2.4 latest-beat suite via dots3 Anthropic /v1/messages.
Priority: multi_aspect M12 M13 M4 M5; long_buffer L2 L5.
Cowrite-test UNTouched (config read-only). 
"""
from pathlib import Path
import json, urllib.request, ssl, time, re, sys

ROOT = Path(r"C:\Users\lenovo\agent-tools\dots_modernist_iter")
SYSTEM = (ROOT / "system" / "SYSTEM_latest.md").read_text(encoding="utf-8").strip()
MA = json.loads((ROOT / "fixtures" / "multi_aspect_fixtures.json").read_text(encoding="utf-8"))["fixtures"]
LB = json.loads((ROOT / "fixtures" / "long_buffer_fixtures.json").read_text(encoding="utf-8"))["fixtures"]
by = {fx["id"]: fx for fx in MA}
by.update({fx["id"]: fx for fx in LB})

PRIORITY = ["M12_no_causal", "M13_precise_liar", "M4_body_force", "M5_shared_object", "LB2_body_force", "LB5_undeep_paper_time"]
if len(sys.argv) > 1:
    PRIORITY = sys.argv[1].split(",")

cfg = json.loads(Path(r"C:\deepseekharness\cowrite-dist\Cowrite-test\app\config.json").read_text(encoding="utf-8"))
url = cfg["base_url"].rstrip("/") + "/v1/messages"
headers = {
    "content-type": "application/json",
    "x-api-key": cfg.get("api_key", ""),
    "anthropic-version": "2023-06-01",
}
ctx = ssl.create_default_context()

TECH_LEAK = re.compile(
    r"读法|我执行|本章|技法|账目|单元|操作名|物证|时间错位|断裂|所指|协变|节点|入口|流动|"
    r"删掉心|眼泪替换|反向工程|变速重写|共同的物|掉出去|让我掉出去|object_regime|控制回落|"
    r"季节词|落点|裂缝|化开|afterbeat|【\d{4}|《从中间|《岔路|闪回闸|零事件|断后|精确的骗子|"
    r"拿掉因此|报告语气|让情节消失|拒绝测试|最新拍"
)
INVENT_AFTERMATH = re.compile(r"修好|至今|撞在一起|接住|合起来|也很美|其实是|物证还在")
SURPRISE = re.compile(r"奇怪|害怕|惊讶|不可思议|太奇")
GLUE = set("的了着在和那这没不没有即使也还再我卡处句悬落回该会可")
ESSAYISH = re.compile(r"因为|所以|因此|说明|意味着|象征|让人觉得|可以看到|这里表明|总结")

def han_count(s):
    return len(re.findall(r"[\u4e00-\u9fff]", s))

def call_dots(system, buffer, temperature=0.55, max_tokens=64):
    user = (
        "作者正在边写边停。请针对下面这段，给一句伴写回复。"
        "只要回复正文，不要元话语、不要解释规则。\n\n【作者文本】\n" + buffer
    )
    body = {
        "model": cfg.get("model", "dots3-note-prev"),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "thinking": {"type": "disabled"},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    parts = [b.get("text") or "" for b in (data.get("content") or []) if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(parts).strip(), data

def lands(fx, reply, silence):
    lid = fx["id"]
    if lid == "M4_body_force":
        if silence:
            return False, "expected body-force speak, got …"
        ok = any(x in reply for x in ("掐", "掌心", "抖", "没端稳", "杯子", "膝盖", "水"))
        return ok, "body force"
    if lid == "M5_shared_object":
        if silence:
            return False, "expected shared-object speak, got …"
        return ("汽笛" in reply), "shared 汽笛"
    if lid == "M12_no_causal":
        if silence:
            return False, "expected perception-chain speak, got …"
        ok = any(x in reply for x in ("雨", "灯", "咳嗽", "铁皮")) and not any(x in reply for x in ("因此", "所以", "因为"))
        return ok, "perception chain"
    if lid == "M13_precise_liar":
        if silence:
            return False, "expected precise-liar surface speak, got …"
        ok = ("左侧" in reply or "右侧" in reply or "未记" in reply) and not any(x in reply for x in ("尸体", "藏", "秘密是"))
        return ok, "回避面／左侧未记"
    if lid == "LB2_body_force":
        if silence:
            return False, "expected body-force speak, got …"
        body = any(x in reply for x in ("掐", "掌心", "抖", "没端稳", "杯子", "膝盖", "水", "袖口", "腕"))
        only_door = ("门" in reply and "响" in reply) and not body
        return body and not only_door, "body force latest"
    if lid == "LB5_undeep_paper_time":
        if silence:
            return True, "silence on latest undeepened paper+time"
        return False, "expected … on latest undeepened; got speak (hijack?)"
    return (han_count(reply) <= 35), "generic"

def judge(fx, reply):
    expect = fx["expect"]
    silence = reply.strip() in ("…", "...", "……", "⋯")
    flags = []
    hc = han_count(reply)
    if silence:
        flags.append("SILENCE")
    if hc > 35:
        flags.append("LEN_FAIL:%d" % hc)
    else:
        flags.append("LEN_OK:%d" % hc)
    if TECH_LEAK.search(reply):
        flags.append("TECH_LEAK")
    if INVENT_AFTERMATH.search(reply):
        flags.append("INVENT_AFTERMATH")
    if ESSAYISH.search(reply):
        flags.append("ESSAYISH")
    if not silence:
        author_set = set(fx["buffer"])
        invent = []
        for ch in reply:
            if "\u4e00" <= ch <= "\u9fff" and ch not in author_set and ch not in GLUE:
                invent.append(ch)
        if invent:
            flags.append("INVENT_CHARS:" + "".join(dict.fromkeys(invent)))

    hard = any(f.startswith("TECH_LEAK") or f.startswith("INVENT_AFTERMATH") or f.startswith("LEN_FAIL") for f in flags)
    ok_land, note = lands(fx, reply, silence)

    if expect == "silence":
        if silence and not hard:
            return "PASS", flags, hc, silence, note
        return "FAIL", flags, hc, silence, note if silence else "expected … got speak"
    # speak / object_surface
    if silence:
        return "FAIL", flags, hc, silence, "expected speak, got …"
    if hard:
        return "FAIL", flags, hc, silence, "hard flags"
    inv = [f for f in flags if f.startswith("INVENT_CHARS:")]
    if inv and len(inv[0].split(":")[1]) >= 3:
        return "FAIL", flags, hc, silence, "invent chars"
    if ok_land:
        if inv:
            return "SOFT_PASS", flags, hc, silence, note + "; minor invent"
        return "PASS", flags, hc, silence, note
    return "FAIL", flags, hc, silence, "miss landing: " + note

def main():
    print("SYSTEM_len", len(SYSTEM), "has_latest", "最新拍优先" in SYSTEM, "v24", "v2.4" in SYSTEM)
    assert "最新拍优先" in SYSTEM
    assert "干净感知链" in SYSTEM or "精确回避面" in SYSTEM
    results = []
    for fid in PRIORITY:
        fx = by[fid]
        print("===", fid, fx["expect"], "===")
        try:
            reply, data = call_dots(SYSTEM, fx["buffer"], 0.55, 64)
            err = None
        except Exception as e:
            reply, data, err = "", {}, str(e)
        if err:
            rec = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                "backend": "dots3",
                "model": cfg.get("model"),
                "system_version": "textbook_verbatim_v2.4",
                "fixture": fid,
                "expect": fx["expect"],
                "raw_reply": "",
                "verdict": "ERROR",
                "flags": ["CALL_FAIL"],
                "note": err,
            }
        else:
            verdict, flags, hc, silence, note = judge(fx, reply)
            rec = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                "backend": "dots3",
                "model": cfg.get("model"),
                "system_version": "textbook_verbatim_v2.4",
                "fixture": fid,
                "year_op": fx.get("year_op"),
                "expect": fx["expect"],
                "raw_reply": reply,
                "han_count": hc,
                "silence": silence,
                "verdict": verdict,
                "flags": flags,
                "note": note,
                "accept_note": fx.get("accept_note"),
                "stop_reason": data.get("stop_reason"),
                "usage": data.get("usage"),
            }
        results.append(rec)
        print("REPLY:", (reply or "")[:100])
        print("VERDICT:", rec["verdict"], rec.get("flags"), rec.get("note"))
        with (ROOT / "run_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        time.sleep(0.5)

    out_dir = ROOT / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "smoke_results_dots3.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    passes = sum(1 for r in results if r["verdict"] in ("PASS", "SOFT_PASS"))
    print("PASS+", passes, "/", len(results))
    print("wrote", out)

if __name__ == "__main__":
    main()
