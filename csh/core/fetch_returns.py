"""从资料库批量下载 4 核分包回传的 jsonl 切片结果。

用法：python fetch_returns.py
产物：%DSH_ROOT%/appearent/package/results/from_4core/<片名>.jsonl

链接是短期签名（q-sign-time 有效期约 2 小时），所以拿到就立刻下。
"""
import json
import os
import subprocess
import sys
import urllib.request

SKILL = ("%USERPROFILE%/AppData/Local/Programs/WorkBuddy/"
         "resources/app.asar.unpacked/resources/plugins/"
         "workbuddy-builtin/skills/library")
PY = sys.executable
DEST = "%DSH_ROOT%/appearent/package/results/from_4core"

# node_id -> 片名（已用 node-info 核对过 title）
NODES = {
    "eylyCpE0lN6k4hnIyiNANt": "E6X_slice01",
    "T7aChpC41Pmt6hFv4ALMV1": "S2L_slice09",
    "UOgOgnA90OfuB0JtVpuD90": "S2L_slice07",
    "hUu1B8tHq96BvTzJDtIybi": "S2L_slice05",
    "PiQSZwKm0lZ7NzyGCIQZGW": "S2L_slice03",
    "eBxby9ALJoQyOh3RqmSfJd": "S2L_slice01",
    "VYRgFjazLqX39tl91aEnRi": "E6X_slice11",
    "3EmjzhSPqr0EQbDvXiVUmq": "E6X_slice09",
    "QZ9Sd7lxjTUKDsFpHKmmrv": "E6X_slice07",
    "6T8ANpTbJbGacTa7BH0E1o": "E6X_slice05",
    "rKnPoYQcqQBC5fXBk2RJOR": "E6X_slice03",
    "OCt9KIXBRYyObAUaE1MLbz": "DPX_slice06",
    "o5tKkZcDxxfj5mGM4F8oWK": "DPX_slice09",
    "27mkikHq0xoVqeDxQIr824": "DPX_slice02",
    "1LkjPCYP249zzehczMHZ4o": "DPX_slice10",
    "btdAlCqrLVItCeKd2BZm4w": "DPX_slice03",
    "HIAfVU6k7WSmDklVSJf8FS": "DPX_slice08",
    "yZy9NWE1ZCbRyWAdxHJLnb": "DPX_slice01",
    "EQQNJxJl0LdmS6FrcK4Brd": "DPX_slice11",
    "NK1lDV3WLzTiWgiLd8ZScb": "DPX_slice04",
    "pce9qDC8WJ8mxhYl0a76bp": "DPX_slice07",
    "wNjlleKRoiS5XIUDNeZS7X": "DPX_slice00",
}


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
    os.makedirs(DEST, exist_ok=True)
    ok, bad = [], []
    for nid, name in NODES.items():
        dst = os.path.join(DEST, name + ".jsonl")
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            print(f"skip {name} (已有)")
            ok.append(name)
            continue
        url = get_link(nid)
        if not url:
            print(f"FAIL {name}: 取不到下载链接")
            bad.append(name)
            continue
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read()
            with open(dst, "wb") as fh:
                fh.write(data)
            nline = data.count(b"\n")
            print(f"ok   {name}: {len(data)} B, {nline} 行")
            ok.append(name)
        except Exception as e:
            print(f"FAIL {name}: {e!r}"[:200])
            bad.append(name)
    print()
    print(f"成功 {len(ok)} / 失败 {len(bad)}")
    if bad:
        print("失败:", bad)


if __name__ == "__main__":
    main()
