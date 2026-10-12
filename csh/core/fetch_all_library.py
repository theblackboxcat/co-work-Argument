"""遍历资料库整棵目录树，收集所有 jsonl 结果节点并下载。

用法：
  python fetch_all_library.py            # 只扫描，打印清单
  python fetch_all_library.py --download # 扫描 + 下载到 results/from_library

与旧的 fetch_returns.py 区别：
  - 不再依赖手填node_id 清单（那会漏掉新上传的批次）
  - 递归进入 folder，逐层list-node
  - 文件名用 node.title 规范化，去掉机器前缀（M5_/M6_/v3_ 等）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

SKILL = ("%USERPROFILE%/AppData/Local/Programs/WorkBuddy/"
         "resources/app.asar.unpacked/resources/plugins/"
         "workbuddy-builtin/skills/library")
SPACE = "space_api.py"
PY = sys.executable
DEST = "%DSH_ROOT%/appearent/package/results/from_library"


def api(name, **kw):
    cmd = [PY, os.path.join(SKILL, SPACE), name]
    for k, v in kw.items():
        cmd += ["--" + k.replace("_", "-"), str(v)]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8")
    for line in reversed(out.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict) and "error" in obj:
            raise RuntimeError(f"{name}: {obj['error']}")
        return obj
    raise RuntimeError(f"{name}: 无有效输出 {out.stdout[:200]!r}")


def walk(space_id, parent=None, depth=0, out=None, seen=None, prefix=""):
    """深度优先遍历，返回 [(node_id, title, kind, ext, path)]。"""
    out = [] if out is None else out
    seen = set() if seen is None else seen
    kw = {"space_id": space_id}
    if parent:
        kw["parent_node_id"] = parent
    data = api("space.workspace.list-node", **kw).get("data", {})
    nodes = data.get("nodes") or []
    for n in nodes:
        nid = n.get("id")
        if nid in seen:
            continue
        seen.add(nid)
        kind = n.get("kind")
        title = n.get("title") or ""
        ext = (n.get("ext") or "").lower()
        if kind == "folder":
            tag = re.sub(r"[^\w一-鿿]+", "", title) or f"f{nid[:6]}"
            out.append((nid, title, kind, ext, prefix))
            walk(space_id, nid, depth + 1, out, seen, prefix + tag + "__")
        else:
            out.append((nid, title, kind, ext, prefix))
    return out


def norm_name(title):
    """去掉扩展名，保留机器前缀（M5_/v3切片_ 等）以免同名覆盖。"""
    t = title.strip()
    t = re.sub(r"\.(jsonl|json|txt|csv)$", "", t, flags=re.I)
    return t or "unnamed"


def get_link(nid):
    out = subprocess.run(
        [PY, os.path.join(SKILL, "drive/get_download_link.py"),
         "--node-id", nid],
        capture_output=True, text=True, encoding="utf-8")
    for line in out.stdout.splitlines():
        if line.startswith("KS_DRIVE_DOWNLOAD "):
            return json.loads(line[len("KS_DRIVE_DOWNLOAD "):])["download_url"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--space-id", default="LWPUd5E2OdOT3UcASirkqL")
    ap.add_argument("--all", action="store_true",
                    help="打印整棵树，不做 CSH 过滤")
    args = ap.parse_args()

    nodes = walk(args.space_id)
    files = [n for n in nodes if n[2] == "drive" and n[3] in ("jsonl", "json", "csv", "txt")]
    folders = [n for n in nodes if n[2] == "folder"]
    print(f"目录树：{len(nodes)} 个节点（{len(folders)} 文件夹 / {len(files)} 文件）\n")
    if args.all:
        for nid, title, kind, ext, path in nodes:
            print(f"  [{kind:6}] {path}{title}")
    else:
        # 只看 CSH 实验相关（S2L / E6X / DPX 切片）
        pat = re.compile(r"(S2L|E6X|DPX)", re.I)
        sel = [n for n in nodes if n[2] == "drive" and pat.search(n[1])]
        print(f"CSH 切片节点 {len(sel)} 个：")
        for nid, title, kind, ext, path in sel:
            print(f"  {path}{title}  ({nid})")
        files = sel

    if not args.download:
        print("\n加 --download 下载")
        return

    os.makedirs(DEST, exist_ok=True)
    ok, bad = [], []
    for nid, title, kind, ext, path in files:
        name = path + norm_name(title)
        dst = os.path.join(DEST, name + "." + (ext or "jsonl"))
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            print(f"skip {name} 已有")
            ok.append(name)
            continue
        url = get_link(nid)
        if not url:
            print(f"FAIL {name}: 取不到下载链接")
            bad.append(name)
            continue
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                data = r.read()
            with open(dst, "wb") as fh:
                fh.write(data)
            print(f"ok   {name}: {len(data)} B, {data.count(10)} 行")
            ok.append(name)
        except Exception as e:
            print(f"FAIL {name}: {e!r}"[:200])
            bad.append(name)
    print(f"\n成功 {len(ok)} / 失败 {len(bad)}")
    if bad:
        print("失败:", bad)
    with open(os.path.join(DEST, "_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump([{"node": n[0], "title": n[1], "kind": n[2], "ext": n[3],
                    "folder": n[4]} for n in nodes], fh,
                  ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()