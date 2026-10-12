# -*- coding: utf-8 -*-
"""DS 网页端朗读桥 · 自动化模块

把文学编辑框的文本路由到 chat.deepseek.com 的 TTS 朗读。

行为：
  1. 用独立的 Edge 配置（tts_profile/）打开 chat.deepseek.com。
  2. 若未登录（落在 /sign_in）→ 窗口停在登录页，返回 need_login。
  3. 若已登录：
       - 发一条前提性请求，让 DS 原样交还文本（不改任何字符），
         再用它的 TTS 朗读这条回复；
       - 等回复出现 → 点回复下方的朗读按钮（播放图标）→ DS 网页窗口发声。
  4. 可选：登录后由外部再次触发朗读。

由 server.py 通过 subprocess 调用，避免把 Playwright 依赖进服务主进程。
本模块假定已安装：pip install playwright，且用系统 Edge。
"""

import json
import os
import re
import sys
import time

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(BASE, 'tts_profile')

# 前提性请求：让 DS 原样交还文本，不增加任何东西，纯用于朗读。
PREMISE = (
    "【朗读任务】请原样、完整地、逐字返回下面双引号内的文本，"
    "不要增删改任何字符，不要加任何解释、不要加标点以外的任何内容。"
    "你返回的这段文本将由 TTS 朗读，所以必须与原文一字不差。\n\n"
)

SIGN_IN_MARKERS = ('sign_in', 'login', '/auth')
LOGIN_BUTTON_TEXTS = ('登录', '发送验证码', '密码登录')


def _is_signin_url(url):
    return any(m in url for m in SIGN_IN_MARKERS)


def _preamble_ok(text):
    """校验文本非空、长度合理。"""
    text = (text or '').strip()
    if not text:
        return False, '空文本'
    if len(text) > 12000:
        return False, '文本过长（>12000 字符），请分段朗读'
    return True, text


def run(text, only_check=False):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE,
            executable_path=EDGE,
            headless=False,
            viewport={'width': 1400, 'height': 900},
            args=['--no-first-run', '--no-default-browser-check',
                  '--autoplay-policy=no-user-gesture-required'],
        )
        # 打开一个明确的页面
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.bring_to_front()
        try:
            page.goto('https://chat.deepseek.com/', wait_until='domcontentloaded', timeout=30000)
        except Exception as e:
            print('__RESULT__' + json.dumps({'ok': False, 'error': '打开 chat.deepseek.com 失败：%s' % e}, ensure_ascii=False))
            ctx.close()
            return
        page.wait_for_timeout(4000)

        url = page.url
        if _is_signin_url(url):
            # 未登录：窗口停在登录页，交给用户
            print('__RESULT__' + json.dumps({
                'ok': False,
                'need_login': True,
                'message': '这台机器的独立朗读配置还没登录过 DeepSeek。\n请在刚弹出的 Edge 窗口里完成登录（扫码或验证码），登录后会自动回到对话页，再点一次朗读即可。',
                'url': url,
            }, ensure_ascii=False))
            # 这里不关闭窗口——让用户能看到并登录。
            # 但为不悬挂资源，我们轮询等待登录（最长若干分钟），登录完成则继续。
            _wait_login_and_continue(ctx, page, text, only_check=only_check)
            return

        if only_check:
            print('__RESULT__' + json.dumps({'ok': True, 'logged_in': True, 'message': '已登录，可朗读'}, ensure_ascii=False))
            ctx.close()
            return

        _do_read(page, text)
        ctx.close()


def _wait_login_and_continue(ctx, page, text, only_check=False, timeout=420):
    """轮询等用户登录。登录成功（URL 离开 sign_in）后继续。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            page.wait_for_timeout(2000)
            url = page.url
            if not _is_signin_url(url):
                # 已登录
                if only_check:
                    print('__RESULT__' + json.dumps({'ok': True, 'logged_in': True,
                                                     'message': '登录成功，可朗读'}, ensure_ascii=False))
                else:
                    _do_read(page, text)
                try:
                    ctx.close()
                except Exception:
                    pass
                return
        except Exception:
            continue
    # 超时：用户没登录，交回控制
    print('__RESULT__' + json.dumps({
        'ok': False,
        'need_login': True,
        'timeout': True,
        'message': '等待登录超时。请在 Edge 窗口登录后，再点一次朗读按钮。',
    }, ensure_ascii=False))
    try:
        ctx.close()
    except Exception:
        pass


def _click_read_aloud(page, reply_text):
    """点击回复卡片下方的朗读（喇叭）按钮。

    关键（已实测）：
    · DS 的朗读按钮是回复卡片下方操作行里的**第 5 个**图标按钮
      （顺序：复制 刷新 赞 踩 → 喇叭 ← 分享），没有文字/aria 属性，
      只能靠"回复文本节点向上找到含≥3个.ds-button的祖先，取第5个"来定位。
    · 必须用**可信用户手势**触发：`element.click()`（JS）是非手势事件，
      会被浏览器自动播放策略拦下、**不出声**；`page.mouse.click(坐标)` 在
      长文本回复时喇叭会被挤到视口下方，坐标点击会落空。
    · 因此这里给喇叭元素打标记 `data-tts-horn`，再用 Playwright 的
      `locator.click()`——它会自动滚动到元素可见并发送可信手势，
      彻底解决"长文本时按钮被挤到页面下面"的失败。
    · 触发成功标志：页面上出现"停止朗读"文本。
    """
    probe = (reply_text or '').strip()[:20]
    # 轮询最多 15 秒，等操作行（≥5 个按钮）出现，并给喇叭打标记
    t0 = time.time()
    marked = False
    while time.time() - t0 < 15:
        try:
            marked = bool(page.evaluate("""(PROBE) => {
              // 优先：从含 PROBE 前缀的回复叶子向上找操作行
              const leaf = [...document.querySelectorAll('*')].filter(e =>
                e.children.length === 0 && e.textContent && e.textContent.trim().startsWith(PROBE));
              let horn = null;
              if (leaf.length) {
                let cur = leaf[leaf.length - 1], buttons = null;
                for (let i = 0; i < 8 && cur; i++) {
                  const b = cur.querySelectorAll && cur.querySelectorAll('.ds-button');
                  if (b.length >= 3) { buttons = b; break; }
                  cur = cur.parentElement;
                }
                if (buttons && buttons.length >= 5) horn = buttons[4];
              }
              // 退化：全页面找"最后一个含≥5个.ds-button的容器"
              if (!horn) {
                const allCont = [...document.querySelectorAll('*')].filter(e => {
                  const b = e.querySelectorAll && e.querySelectorAll('.ds-button');
                  return b && b.length >= 5;
                });
                const cont = allCont[allCont.length - 1];
                if (cont) horn = cont.querySelectorAll('.ds-button')[4];
              }
              if (!horn) return false;
              // 打标记，供后续 locator.click 使用
              horn.setAttribute('data-tts-horn', '1');
              return true;
            }""", probe))
            if marked:
                break
        except Exception:
            pass
        page.wait_for_timeout(800)

    if not marked:
        print('[tts] horn locate failed after 15s', flush=True)
        return False
    # 用 locator.click：自动滚动到可见 + 可信手势，避开视口外坐标问题
    try:
        loc = page.locator('[data-tts-horn]').first
        loc.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        loc.click()
    except Exception as e:
        print('[tts] locator click err, fallback mouse:', e, flush=True)
        # 兜底：坐标点击
        try:
            r = loc.bounding_box()
            if r:
                page.mouse.click(r['x'] + r['width'] / 2, r['y'] + r['height'] / 2)
        except Exception:
            return False
    # 点击后短暂观察：短文可能 1.5 秒内就读完，"停止朗读"会快速消失，
    # 所以只要求"定位并点击了喇叭"即视为触发成功。
    page.wait_for_timeout(400)
    return True


def _find_input_and_send(page, text):
    """把消息填入 DS 输入框并发送。

    DS 输入框在独立配置下是 <textarea>（登录后默认形态），
    也可能是 contenteditable div。两者都试。
    """
    locs = [
        ("textarea", page.locator("textarea").first),
        ("contenteditable", page.locator("div[contenteditable='true']").first),
        ("textbox", page.locator("[role='textbox']").first),
    ]
    for name, editor in locs:
        try:
            if editor.count() and editor.is_visible():
                editor.click()
                page.wait_for_timeout(300)
                page.keyboard.press('ControlOrMeta+A')
                page.keyboard.insert_text(text)
                page.wait_for_timeout(400)
                page.keyboard.press('Enter')
                print('[tts] used input:', name, flush=True)
                return True
        except Exception:
            continue
    return False


def _do_read(page, text):
    """把文本发给 DS，等回复出现后**停在原地**，让用户自己点播放。

    不做自动点击喇叭、不做朗读监听、不自动关闭——砍掉"获得 DS 回复后
    的监听点击关闭"这一段。脚本保持窗口打开，直到用户点完播放/手动关窗，
    或到达保持超时上限。
    """
    try:
        full = PREMISE + text
        if not _find_input_and_send(page, full):
            print('__RESULT__' + json.dumps({'ok': False, 'error': '找不到 DeepSeek 输入框（页面结构可能已变）'}, ensure_ascii=False))
            return
        # 等 DS 回复出现（轮询找新增的消息文本块）
        replied = _wait_reply(page, text, timeout=60)
        if not replied:
            print('__RESULT__' + json.dumps({'ok': False, 'error': '等待 DeepSeek 回复超时（可能被限流或结构变化）'}, ensure_ascii=False))
            return
        # 获得回复后：停在这里。提示用户自己点播放，窗口保持打开。
        print('__RESULT__' + json.dumps({
            'ok': True,
            'message': '已把文本发给 DeepSeek，回复已出现。\n请在 Edge 窗口里点回复下方的播放/朗读按钮收听，'
                       '窗口会保持打开，等你点完播放键。',
        }, ensure_ascii=False))
        _hold_window(page)
    except Exception as e:
        print('__RESULT__' + json.dumps({'ok': False, 'error': '朗读流程异常：%s' % e}, ensure_ascii=False))


def _hold_window(page, timeout=600):
    """保持窗口打开，等用户自己点播放并听完；直到用户手动关窗或超时。

    不再自动点击/监听朗读状态——只负责把窗口停住，让用户操作。
    用户听完后自己关掉 Edge 窗口即可，脚本检测到窗口关闭即收尾。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if page.is_closed():
                print('[tts] window closed by user, done', flush=True)
                return
        except Exception:
            return
        page.wait_for_timeout(2000)
    print('[tts] hold timeout reached, closing', flush=True)


def _wait_reply(page, text, timeout=60):
    """等一条形似原样交还的回复出现。"""
    probe = (text[:40] or '').strip()
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            page.wait_for_timeout(1500)
            body = page.inner_text('body') or ''
            # 回复出现标志：文本近似匹配（朗读按钮出现前，页面不含"停止朗读"）
            if probe and probe in body:
                return True
        except Exception:
            continue
    return False


def main():
    # 参数：--text-file <path> [--only-check]
    args = sys.argv[1:]
    text = ''
    only_check = False
    for i, a in enumerate(args):
        if a == '--only-check':
            only_check = True
        elif a == '--text-file' and i + 1 < len(args):
            p = args[i + 1]
            with open(p, encoding='utf-8') as f:
                text = f.read()
    if not text and not only_check:
        print('__RESULT__' + json.dumps({'ok': False, 'error': '没有文本'}, ensure_ascii=False))
        return
    if only_check:
        run('', only_check=True)
    else:
        ok, val = _preamble_ok(text)
        if not ok:
            print('__RESULT__' + json.dumps({'ok': False, 'error': val}, ensure_ascii=False))
            return
        run(val)


if __name__ == '__main__':
    main()
