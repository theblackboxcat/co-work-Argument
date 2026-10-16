# -*- coding: utf-8 -*-
"""文学工作台的工具层：上网查资料、查 GitHub、找本地 skill。

零第三方依赖（只用标准库 urllib / re / html），与项目其余部分一致。

── 为什么走"标签协议"，而不是原生 function calling ──────────────
伴写那层的 providers.py 明确写着"不需要 tool calling"，原因在那儿成立：
它只有一个调用形状（system + user → 一段正文）。但文学模式是另一回事——
猫猫要的是"我提一个复杂需求，它自己去找"，那必须有工具。

没走原生 function calling，两个理由：

1. **默认模型是内网端点**（dots3，Anthropic 格式）。它的工具支持是什么样
   我们不知道，而 native tools 要在 OpenAI / Anthropic 两套协议上各写一遍，
   还要各自处理 tool_result 的形状——为了一个不确定的能力，把适配层加厚一倍，
   不划算。
2. **标签协议对模型一视同仁**。换成任何一家 provider 都能用，包括本地 Ollama。

代价是它靠模型照格式输出，比 native 脆。所以解析器写得宽松（认几种形状），
并且**最多循环 3 轮**——模型没照格式来，就当它这次没用工具，照常回答。

── 网络 ────────────────────────────────────────────────
出网走环境变量里的代理（urllib 自动读 http_proxy / https_proxy）。
实测（2026-09-17 本机）：GitHub API 可达；Bing 可达；
DuckDuckGo 在本机的代理隧道上 502，所以搜索用 Bing。
"""
import base64
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120 Safari/537.36')
TIMEOUT = 20
MAX_FETCH = 6000          # 单页抓回来给模型看的字数上限
SKILL_DIRS = [
    os.path.expanduser('~/.workbuddy/skills'),
]


class ToolError(Exception):
    """工具执行失败。**它不是故障**：工具不可用不等于这次回答不了，
    上层应该把它作为一条"没查到"回喂给模型，让它自己决定怎么办。"""


# ---------------------------------------------------------------- 基础
def _get(url, headers=None, timeout=TIMEOUT):
    if not url.lower().startswith(('http://', 'https://')):
        raise ToolError('只认 http/https，别的协议不给抓：%s' % url[:60])
    host = (urllib.parse.urlparse(url).hostname or '').lower()
    if host in ('169.254.169.254', 'metadata.google.internal'):
        raise ToolError('这个地址不给抓：%s' % host)
    req = urllib.request.Request(url, headers=dict(
        {'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'},
        **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except Exception as e:
        raise ToolError('%s → %s：%s' % (url[:70], type(e).__name__, str(e)[:120]))
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('utf-8', 'replace')


def _get_json(url, headers=None, timeout=TIMEOUT):
    t = _get(url, headers, timeout)
    try:
        return json.loads(t)
    except Exception:
        raise ToolError('返回不是 JSON：%s' % t[:120])


def _strip_tags(s):
    s = re.sub(r'(?is)<(script|style|noscript)\b.*?</\1>', ' ', s)
    s = re.sub(r'(?is)<br\s*/?>', '\n', s)
    s = re.sub(r'(?is)</(p|div|li|h[1-6]|tr)>', '\n', s)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = re.sub(r'[ \t\u00a0]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def _cut(s, n=MAX_FETCH):
    s = (s or '').strip()
    if len(s) <= n:
        return s
    return s[:n] + '\n…（后面还有，已截断）'


# ---------------------------------------------------------------- 工具
def web_search(q, n=5):
    """搜一段网页，回标题 + 链接 + 摘要。**摘要是二手的**，要引用得再 fetch。"""
    q = (q or '').strip()
    if not q:
        raise ToolError('没给关键词')
    url = ('https://www.bing.com/search?q=%s&setlang=zh-CN&count=%d'
           % (urllib.parse.quote(q), max(3, min(int(n or 5), 10))))
    h = _get(url)
    out = []
    for b in re.findall(r'<li class="b_algo".*?</li>', h, re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not m:
            continue
        p = re.search(r'<p[^>]*>(.*?)</p>', b, re.S)
        out.append({'title': _strip_tags(m.group(2))[:120],
                    'url': html.unescape(m.group(1)),
                    'snippet': _strip_tags(p.group(1))[:300] if p else ''})
        if len(out) >= n:
            break
    if not out:
        raise ToolError('没搜到结果（Bing 的版式可能变了，或这次没结果）')
    return '\n'.join('[%d] %s\n    %s\n    %s'
                     % (i + 1, r['title'], r['url'], r['snippet'])
                     for i, r in enumerate(out))


def web_fetch(url, n=MAX_FETCH):
    """抓一个页面的正文。搜索结果的摘要不算数，要引用原文得抓下来看。"""
    return _cut(_strip_tags(_get((url or '').strip())), n)


def gh_search(q, kind='repositories', n=5):
    """搜 GitHub。kind: repositories（默认）/ issues。不需要 token（有速率限制）。"""
    q = (q or '').strip()
    if not q:
        raise ToolError('没给关键词')
    kind = 'issues' if kind == 'issues' else 'repositories'
    url = ('https://api.github.com/search/%s?q=%s&per_page=%d&sort=%s'
           % (kind, urllib.parse.quote(q), max(1, min(int(n or 5), 10)),
              'updated' if kind == 'issues' else 'stars'))
    d = _get_json(url, {'Accept': 'application/vnd.github+json'})
    items = d.get('items') or []
    if not items:
        return 'GitHub 上没搜到：%s' % q
    if kind == 'issues':
        return '\n'.join('%s · %s\n    %s'
                         % (i.get('title', '')[:110], i.get('html_url', ''),
                            (i.get('body') or '')[:200].replace('\n', ' '))
                         for i in items)
    return '\n'.join('%s ★%s · %s\n    %s\n    %s'
                     % (i.get('full_name', ''), i.get('stargazers_count', 0),
                        (i.get('language') or '-'), (i.get('description') or '')[:160],
                        i.get('html_url', ''))
                     for i in items)


def gh_list(owner, repo, path='', ref=''):
    """列一个 GitHub 仓库的目录。找东西时先看有什么，再决定读哪个。"""
    if not (owner and repo):
        raise ToolError('要给 owner 和 repo')
    url = 'https://api.github.com/repos/%s/%s/contents/%s' % (
        owner, repo, urllib.parse.quote((path or '').strip('/')))
    if ref:
        url += '?ref=' + urllib.parse.quote(ref)
    d = _get_json(url, {'Accept': 'application/vnd.github+json'})
    if isinstance(d, dict):
        raise ToolError('那是个文件不是目录，用 gh_file 读它：%s' % (d.get('path') or path))
    return '\n'.join(('%s/  %s' % (i.get('name'), i.get('path'))
                      if i.get('type') == 'dir'
                      else '%s  %s' % (i.get('name'), i.get('size')))
                     for i in d[:200])


def gh_file(owner, repo, path, ref=''):
    """读 GitHub 上一个文件的内容。走 contents API（base64），
    实测 raw.githubusercontent 在本机代理上会超时。"""
    if not (owner and repo and path):
        raise ToolError('要给 owner、repo、path')
    url = 'https://api.github.com/repos/%s/%s/contents/%s' % (
        owner, repo, urllib.parse.quote(path.strip('/')))
    if ref:
        url += '?ref=' + urllib.parse.quote(ref)
    d = _get_json(url, {'Accept': 'application/vnd.github+json'})
    if not isinstance(d, dict) or d.get('type') != 'file':
        raise ToolError('那不是个文件：%s' % path)
    try:
        body = base64.b64decode((d.get('content') or '').replace('\n', '')).decode('utf-8', 'replace')
    except Exception as e:
        raise ToolError('内容解不出来：%s' % e)
    return _cut(body, MAX_FETCH * 2)


def find_skill(q=''):
    """找本地装着的 skill（agent）。扫 SKILL.md 的 frontmatter：name + description。

    这是唯一一个**不出网**的工具——它找的正是"本机已经会干的事"。
    """
    q = (q or '').strip().lower()
    found = []
    for root in SKILL_DIRS:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name, 'SKILL.md')
            if not os.path.isfile(p):
                continue
            try:
                with open(p, encoding='utf-8', errors='replace') as f:
                    head = f.read(4000)
            except Exception:
                continue
            meta = {}
            m = re.match(r'\s*---\s*\n(.*?)\n---', head, re.S)
            if m:
                for k in ('name', 'description'):
                    mm = re.search(r'^%s:\s*(.+)$' % k, m.group(1), re.M)
                    if mm:
                        meta[k] = mm.group(1).strip().strip('"\'')

            meta = {k: v for k, v in meta.items() if isinstance(v, str)}
            desc = re.sub(r'\s+', ' ', meta.get('description', '') or '')
            title = meta.get('name') or name
            blob = (title + ' ' + desc + ' ' + name).lower()
            if q and not any(w in blob for w in re.split(r'[\s,，、]+', q) if w):
                continue
            found.append('%s —— %s\n    路径：%s' % (title, desc[:200], p))
    if not found:
        return ('本机没找到匹配的 skill' + ('（关键词：%s）' % q if q else '')
                + '。装着的都在 ~/.workbuddy/skills/ 下。')
    return '\n'.join(found)


# ---------------------------------------------------------------- 注册表
# ---------------------------------------------------------------- LOFTER
# ── 为什么只做不登录的这一套 ────────────────────────────────
# 实测（2026-09-18）：按 tag 搜索、某博客的合集、单篇全文——**都不用登录**。
# 登录只多解锁"我的"那部分（订阅、浏览历史、自己仅自己可见的）。
# 而登录态是要拿她的 cookie 去换的，一旦被风控，封的是她自己的号。
# 所以这里**不带任何登录态**，只走公开接口，并且：
#   1. 节流（两次请求之间至少隔 1.2 秒）——这是别人的服务器；
#   2. 撞上有访问限制的文章就明说"拿不到"，**不绕**；
#   3. 单次最多 30 条，不做全站批量翻页（tag 那边本来也有 100 页硬上限）。
LOFTER_API = 'https://api.lofter.com'
LOFTER_HDR = {
    'User-Agent': 'LOFTER-Android 7.6.12 (V2272A; Android 13; null) WIFI',
    'Accept-Encoding': 'identity',   # 不写这个会拿回 br/gzip，标准库解不开 brotli
    'Content-Type': 'application/x-www-form-urlencoded',
    'lofproduct': 'lofter-android-7.6.12',
}
_lofter_last = [0.0]
LOFTER_GAP = 1.2     # 两次请求之间至少隔这么久


def _lofter_call(path, data):
    """打一次 LOFTER 接口：先节流，再只认 meta.status == 200。

    注意"接口活着 ≠ 能用"：DWR 那个老接口现在也返回 200，
    但回的是业务错误。所以看的是 meta.status，不是 HTTP 状态码。"""
    gap = LOFTER_GAP - (time.time() - _lofter_last[0])
    if gap > 0:
        time.sleep(gap)
    req = urllib.request.Request(
        LOFTER_API + path + '?product=lofter-android-7.6.12',
        data=data.encode('utf-8'), headers=LOFTER_HDR)
    try:
        raw = urllib.request.urlopen(req, timeout=TIMEOUT).read()
    finally:
        _lofter_last[0] = time.time()
    try:
        d = json.loads(raw.decode('utf-8', 'ignore'))
    except Exception:
        raise ToolError('返回的不是 JSON（接口可能又变了）')
    meta = d.get('meta') or {}
    if meta.get('status') != 200:
        raise ToolError('接口说：%s'
                        % (meta.get('msg') or meta.get('code') or '不成'))
    return d.get('response') or {}


def _lofter_tidy(s):
    """LOFTER 的正文是 `<p>` 套着 `<br/>`，_strip_tags 剥完会留下一串只含空格的行。

    读起来像断气。所以把行首行尾的空白吃干净，再让空行最多留一个——
    **段落之间仍留一个空行**，那是原文的结构，不能抹平。"""
    s = re.sub(r'[ \t\u00a0]*\n[ \t\u00a0]*', '\n', s or '')
    s = re.sub(r'\n{2,}', '\n\n', s)
    return s.strip()


def _lofter_domain(name):
    n = re.sub(r'^(?:https?://)?(?:www\.)?', '', (name or '').strip())
    n = re.sub(r'\.lofter\.com.*$', '', n).strip('/ ')
    if not n:
        raise ToolError('没给博客名')
    return n


def _lofter_author(p):
    """一篇文章**自己的**署名博客名。

    为什么要它：**合集不认人**。一个合集里可以塞进别的博客的文章——实测
    2026-09-19，`drunkfloats` 的「亦梦罐子」里混着 42 篇别人的东西。所以
    "合集里的文章" ≠ "这个账号的作品"，得看文章自己带的 `blogInfo`。

    另外**链接也必须用它**：permalink 只是 `postid_blogid`，拼 URL 时前半截
    要的是博客名，拿发起查询的那个域名去拼，混进来的那部分会全拼错。
    """
    bi = p.get('blogInfo') or {}
    return (bi.get('blogName') or '').strip()


def _lofter_is_mine(p, domainname):
    """这篇是不是**这个号自己**发的。

    署名拿不到时**算自己的**：宁可漏标一个，也不要把她的东西标成别人的——
    标错比不标更难收拾（她会以为整理出来的不是她写的）。
    """
    au = _lofter_author(p)
    return (not au) or au.lower() == (domainname or '').lower()


def _lofter_images(p):
    """取一篇的图片链接。

    **图片不在正文 HTML 里**——正文是 `<p>` 文字，图挂在 `photoLinks` 字段上，
    而且那字段是**双重编码**的：值本身是个 JSON 字符串，得再解一次。
    有些帖子正文只有几个字，文章其实全在图里；不把图列出来，
    她会以为这篇是空的。
    """
    raw = p.get('photoLinks') or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    urls = []
    for it in (raw or []):
        if not isinstance(it, dict):
            continue
        u = it.get('orign') or it.get('raw') or it.get('middle') or it.get('small')
        if u:
            urls.append(re.sub(r'\?.*$', '', u))   # 去掉缩略参数，给原图
    return urls


def lofter_post(url):
    """给一个 LOFTER 文章链接，出全文（标题 / 标签 / 时间 / 正文）。

    不用登录，也**只拿公开可见的**——撞上限权文章就明说拿不到。"""
    m = re.search(r'(?:https?://)?([A-Za-z0-9\-_]+)\.lofter\.com/post/'
                  r'([0-9a-fA-F]+)_([0-9a-fA-F]+)', (url or '').strip())
    if not m:
        raise ToolError('不像一个 LOFTER 文章链接：%s' % (url or '(空)'))
    blog_name, blog_id, post_id = m.group(1), int(m.group(2), 16), int(m.group(3), 16)
    r = _lofter_call('/oldapi/post/detail.api',
                     'targetblogid=%d&supportposttypes=1,2,3,4,5,6&offset=0'
                     '&requestType=1&postdigestnew=1&postid=%d&blogId=%d'
                     '&checkpwd=1&needgetpoststat=1' % (blog_id, post_id, blog_id))
    posts = r.get('posts') or []
    if not posts:
        raise ToolError('接口没返回这篇文章')
    p = posts[0].get('post') or {}
    if p.get('allowView') or p.get('payView'):
        raise ToolError('这篇有访问限制（要权限或要付费）——不绕，只能拿公开可见的')
    body = _cut(_lofter_tidy(_strip_tags(p.get('content') or p.get('digest') or '')),
                MAX_FETCH)
    if not body:
        raise ToolError('这篇没拿到正文（可能是纯图片，或者被限制了）')
    head = []
    if p.get('title'):
        head.append('标题：' + p['title'])
    if p.get('tag'):
        head.append('标签：' + p['tag'])
    if p.get('publishTime'):
        head.append('发布：' + time.strftime('%Y-%m-%d',
                                             time.localtime(p['publishTime'] / 1000)))
    head.append('链接：https://%s.lofter.com/post/%s'
                % (blog_name, p.get('permalink') or ''))
    out = '\n'.join(head) + '\n\n' + body

    # 有的帖子文字就几个字，文章其实在图上。**正文短而图多时要明说**，
    # 否则她看到一两句正文，会以为这篇本来就没写什么。
    imgs = _lofter_images(p)
    if imgs:
        tail = []
        if len(body) < 200:
            tail.append('\n\n注意：这篇的正文只有 %d 字，**东西主要在图里**（%d 张）。'
                        % (len(body), len(imgs)))
        tail.append('\n\n图片（%d 张，原图，可以一次给 read_image 一串）：' % len(imgs))
        tail += ['  %d. %s' % (i, u) for i, u in enumerate(imgs[:10], 1)]
        if len(imgs) > 10:
            tail.append('  …还有 %d 张' % (len(imgs) - 10))
        out += '\n'.join(tail)
    return out


# ── 合集接口的三个坑（都是实测踩出来的，别照着"直觉"改回去）──
# ① `postCount` 可能是 **0**。`c.get('postCount') or '?'` 会把"空合集"写成
#    "篇数不明"——模型看到"不明"就会去翻它，白花一轮。所以判 `is not None`。
# ② **"空"和"id 错"是两回事**。合集 detail 拿不到文章时，原来说的是
#    "collection_id 对吗？"，实测那个合集的 postCount 就是 0 —— 它本来就是空的。
#    把"空"说成"可能 id 错了"，模型会去重试或换 id，又是一轮。
# ③ `collections` 响应里**没有任何 total／分页字段**（只有一个 collections 数组），
#    所以本地切片就是**静默截断**：切完不吭声，看的人以为这就是全部。要切就得说。

def _lofter_collections(domain):
    """这个博客的合集清单（**原样**，不切片——切片是调用方的事）。"""
    r = _lofter_call('/v1.1/postCollection.api',
                     'blogdomain=%s&method=getCollectionList&needViewCount=1' % domain)
    return r.get('collections') or []


def _lofter_day(ms):
    try:
        return time.strftime('%Y-%m-%d', time.localtime(ms / 1000)) if ms else ''
    except Exception:
        return ''


def _lofter_coll_items(collection_id, limit):
    """一个合集里的文章。实测 limit 给到 100 也照给（89 篇的合集一次拿全），
    所以不必翻页——一个合集一个请求。"""
    return _lofter_call('/v1.1/postCollection.api',
                        'method=getCollectionDetail&offset=0&limit=%d'
                        '&collectionid=%s&order=1' % (limit, collection_id))


def lofter_blog(name, collection_id=None, limit=15):
    """列一个 LOFTER 博客的合集；给了 collection_id，就列那个合集里的文章。

    ⚠️ 合集 ≠ 作品：这里只有"归进了合集的文章"。要"整理一个账号的作品"，
    用 lofter_works —— 一个个翻合集，工具轮次会不够（见那个函数的说明）。"""
    domainname = _lofter_domain(name)
    domain = domainname + '.lofter.com'
    limit = max(1, min(int(limit or 15), 30))
    if collection_id:
        r = _lofter_coll_items(collection_id, limit)
        items = r.get('items') or []
        c = r.get('collection') or {}
        pc = c.get('postCount')
        if not items:
            if pc == 0:
                raise ToolError('这个合集是空的（postCount=0），里面还没有文章')
            raise ToolError('这个合集没拿到文章（postCount=%s，可能没公开）'
                            % ('?' if pc is None else pc))
        listed = items[:limit]
        cother = sum(1 for it in listed
                     if not _lofter_is_mine(it.get('post') or {}, domainname))
        out = ['合集：%s · 共 %s 篇' % (c.get('name') or collection_id,
                                        '?' if pc is None else pc)]
        if cother:
            out.append('⚠️ 合集不认人：这 %d 篇里有 %d 篇是别人的，标了 @作者，'
                       '链接指回他本人的博客。' % (len(listed), cother))
        for i, it in enumerate(listed, 1):
            p = it.get('post') or {}
            day = _lofter_day(p.get('publishTime'))
            au = _lofter_author(p)
            mine = _lofter_is_mine(p, domainname)
            out.append('[%d] %s%s%s\n    post_id=%s · https://%s.lofter.com/post/%s'
                       % (i, (p.get('title') or '（无标题）')[:60],
                          (' · ' + day) if day else '',
                          ('' if mine else ' · @' + (au or '?')),
                          p.get('id'), au or domainname, p.get('permalink') or ''))
        return '\n'.join(out)
    colls = _lofter_collections(domain)
    if not colls:
        raise ToolError('这个博客没有公开的合集：%s' % domain)
    lines = ['博客：%s · 共 %d 个合集' % (domain, len(colls))]
    for c in colls[:limit]:
        n = c.get('postCount')
        lines.append('· %s（%s 篇）· collection_id=%s'
                     % (c.get('name') or '（无名）',
                        '?' if n is None else n, c.get('id')))
    if len(colls) > limit:
        lines.append('（只列了前 %d 个，还有 %d 个**没列**——要看就给 limit，'
                     '或者用 lofter_works 一次列全）'
                     % (limit, len(colls) - limit))
    lines.append('⚠️ 合集 ≠ 作品：没归进合集的文章，这个接口看不到。')
    return '\n'.join(lines)


_LOFTER_WORKS_MAX = 40000     # 清单的字符上限；超了**明说**截到哪里


def lofter_works(name, max_collections=20, per_collection=100):
    """把一个 LOFTER 博客**所有合集里的文章**一次列出来。

    为什么要它：`lofter_blog` 一次只给一个合集，而模型的工具轮次是有限的
    （`LIT_MAX_ROUNDS = 4`）。一个号十几个合集，一个个翻必然在中途被收口，
    于是"整理这个账号的作品"就退化成"我翻到的那一篇"——2026-09-19 实测：
    她问 `整理这个账号的作品 <主页>`，拿回来的是一首诗。这个工具把十几
    次请求收进**一次调用**。

    ⚠️ 边界（会写进返回里，不藏）：只覆盖**归进了合集的文章**。
    没归集的那部分，公开接口看不到——主页作品流和归档页 `/view` 都要登录，
    而这一套按设计**不携带任何登录态**（登录态一旦被风控，封的是她自己的号）。
    真要列全，得另找路子，不能在"不登录"这条底线上开口子。
    """
    domainname = _lofter_domain(name)
    domain = domainname + '.lofter.com'
    colls = _lofter_collections(domain)
    if not colls:
        raise ToolError('这个博客没有公开的合集：%s' % domain)
    # 最近的合集排前面——她的新东西在哪儿，先让看的人看见
    colls.sort(key=lambda c: (c.get('lastPublishTime') or c.get('updateTime') or 0),
               reverse=True)
    todo = colls[:max(1, int(max_collections or 20))]
    rest = len(colls) - len(todo)
    per = max(1, min(int(per_collection or 100), 100))

    seen, groups, empty, trouble = {}, [], [], []
    nick = ''
    for c in todo:
        cid, cname = c.get('id'), c.get('name') or ('合集 %s' % c.get('id'))
        if c.get('postCount') == 0:
            # 空合集**不打接口**：省一次请求，也省掉 1.2 秒的等
            empty.append(cname)
            continue
        try:
            r = _lofter_coll_items(cid, per)
        except Exception as e:
            trouble.append('%s（%s）' % (cname, str(e)[:50]))
            continue
        if not nick:
            nick = ((r.get('blogInfo') or {}).get('blogNickName') or '')
        posts = []
        for it in (r.get('items') or []):
            p = it.get('post') or {}
            if not p.get('id') or p['id'] in seen:
                continue          # 同一篇挂两个合集时只留一次
            seen[p['id']] = 1
            posts.append(p)
        if posts:
            groups.append((cname, posts))
        else:
            trouble.append('%s（一篇都没拿到）' % cname)

    total = len(seen)
    other = sum(1 for _, ps in groups for p in ps
                if not _lofter_is_mine(p, domainname))
    out = ['博客：%s%s' % (domain, ('（%s）' % nick) if nick else ''),
           '合集 %d 个里有文章的 %d 个 · 文章 %d 篇（去重后：本人 %d 篇，'
           '合集里混着别人的 %d 篇）'
           % (len(colls), len(groups), total, total - other, other),
           '⚠️ 这里只有**归进了合集的文章**。没归集的那部分公开接口看不到：'
           'LOFTER 的主页作品流和归档页 /view 都要登录，而这个工具**不携带登录态**'
           '（登录态被风控，封的是登录的那个号）。']
    if other:
        out.append('⚠️ 合集不认人：上面那 %d 篇是别人发在这个号合集里的，标了 @作者，'
                   '链接也指回他本人的博客。要"这个账号的作品"，看没标 @ 的那些。'
                   % other)
    if rest > 0:
        out.append('（还有 %d 个合集没翻——把 max_collections 放大可以继续）' % rest)

    body = []
    for cname, posts in groups:
        posts.sort(key=lambda p: p.get('publishTime') or 0, reverse=True)
        cother = sum(1 for p in posts if not _lofter_is_mine(p, domainname))
        body.append('\n【%s】%d 篇%s'
                    % (cname, len(posts),
                       ('（本人 %d · 别人 %d）' % (len(posts) - cother, cother))
                       if cother else ''))
        for i, p in enumerate(posts, 1):
            day = _lofter_day(p.get('publishTime'))
            au = _lofter_author(p)
            mine = _lofter_is_mine(p, domainname)
            body.append('[%d] %s%s%s\n    https://%s.lofter.com/post/%s'
                        % (i, (p.get('title') or '（无标题）')[:70],
                           (' · ' + day) if day else '',
                           ('' if mine else ' · @' + (au or '?')),
                           au or domainname, p.get('permalink') or ''))
    if empty:
        body.append('\n【空合集】' + '、'.join(empty))
    if trouble:
        body.append('\n【没拿到】' + '、'.join(trouble))

    text = '\n'.join(out + body)
    if len(text) > _LOFTER_WORKS_MAX:
        text = (text[:_LOFTER_WORKS_MAX]
                + '\n\n…（清单太长，在这里截住了；要剩下的就按合集查 '
                  'lofter_blog）')
    return text


# ---------------------------------------------------------------- 读图上的字
# ── 读图的两级火箭 ─────────────────────────────────────────────
# 第一级：**RapidOCR**（PaddleOCR 的 ONNX 版）。中文 OCR 的正规军。
#   实测（2026-09-18）：20 行长图 3.7 秒全部读出；之前 ollama 全军覆没的
#   那些图，它一张不落。装在哪个解释器里由 _OCR_PY_CANDIDATES 按顺序找
#   （环境变量 LIT_OCR_PY → 自己 → 系统 python C:\Python314）。
# 第二级：ollama 的 qwen2.5vl:3b。只在两种时候上场：
#   ① 带了 ask（要"问图"，不是"抄字"）；② RapidOCR 一行字都没读到
#   （可能是张画，也可能 OCR 真瞎了），让它兜一次底。
#
# ── 为什么是子进程，不是直接 import ────────────────────────────
# 本文件承诺零第三方依赖，而网页服务又是托管 python 3.13.12 起的——rapidocr
# 装在系统 python 里，两边对不上。所以 OCR 走子进程：找一个带 rapidocr 的
# 解释器，把图片路径喂过去，JSON 收回来。找不到解释器就整级跳过，全靠第二级。
#
# ── 顺带记一笔 qwen2.5vl:3b 的坑（别再回去试它读字了）─────────
# 它读字极不稳定，而且是**稳定地不稳定**：同一张清晰的字图跑三遍都
# "图上没有字"，换一张内容几乎一样的就一字不差；长图整张看不见。
# 跟长宽、字号、字数都对不上——就是个 3B 小模型不肯好好认字。只配当兜底。
_OCR_PY_CANDIDATES = (
    os.environ.get('LIT_OCR_PY'),
    # 先问自己这个解释器：便携版把 rapidocr 装进同一个 venv 时，这一条就命中，
    # 不必再去认某台机器上那个绝对路径。
    sys.executable,
    r'C:\Python314\python.exe',
)
_OCR_PY = None            # None=还没探；''=探过了没有；非空=可用解释器

# 在带 rapidocr 的解释器里跑的一小段：stdin 收路径，stdout 吐每张图的行。
# 行序按框的左上角排（先上后左），RapidOCR 自己的顺序偶尔会乱。
_OCR_RUNNER = r'''
import sys, json
import rapidocr_onnxruntime as R
eng = R.RapidOCR()
data = json.load(sys.stdin)
out = []
for p in data["paths"]:
    try:
        res, _ = eng(p)
        items = []
        if res:
            def key(it):
                b = it[0]
                return (min(pt[1] for pt in b), min(pt[0] for pt in b))
            for it in sorted(res, key=key):
                items.append(str(it[1]))
        out.append({"path": p, "lines": items})
    except Exception as e:
        out.append({"path": p, "lines": [], "err": str(e)[:120]})
json.dump(out, sys.stdout, ensure_ascii=False)
'''


def _ocr_python():
    """找一个带 rapidocr 的解释器。没有就返回 None（第一级整个跳过）。"""
    if _OCR_PY is not None:
        return _OCR_PY or None
    cands = []
    for c in _OCR_PY_CANDIDATES:
        c = (c or '').strip()
        if c and os.path.exists(c) and c not in cands:
            cands.append(c)
    w = shutil.which('python')
    if w and w not in cands:
        cands.append(w)
    for c in cands:
        try:
            r = subprocess.run([c, '-c', 'import rapidocr_onnxruntime'],
                               capture_output=True, timeout=60)
            if r.returncode == 0:
                globals()['_OCR_PY'] = c
                return c
        except Exception:
            pass
    globals()['_OCR_PY'] = ''
    return None


def _rapid_ocr(paths):
    """批量跑 RapidOCR。返回 {路径: [行, ...]}；引擎不可用/跑挂了返回 None。"""
    py = _ocr_python()
    if not py or not paths:
        return None
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    try:
        r = subprocess.run([py, '-c', _OCR_RUNNER],
                           input=json.dumps({'paths': paths}).encode('utf-8'),
                           capture_output=True,
                           timeout=40 + 15 * len(paths), env=env)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    try:
        items = json.loads(r.stdout.decode('utf-8', 'ignore'))
    except Exception:
        return None
    return {it['path']: it.get('lines') or [] for it in items}
def _ollama_base():
    """ollama 的地址。环境变量里那个不能直接拿来连：

    · 它常常写成 `0.0.0.0:11434`——**没有协议头**，urllib 认不出
      （报"unknown url type: 0.0.0.0"，看着像网络坏了，其实是地址没写全）；
    · 而且 `0.0.0.0` 是"监听所有网卡"，不是用来连的地址。连自己要用 127.0.0.1。
    """
    h = (os.environ.get('OLLAMA_HOST') or 'http://127.0.0.1:11434').strip()
    if '://' not in h:
        h = 'http://' + h
    return h.replace('0.0.0.0', '127.0.0.1').rstrip('/')


OLLAMA = _ollama_base()
VISION_MODEL = os.environ.get('LIT_VISION_MODEL', 'qwen2.5vl:3b')
IMG_MAX_BYTES = 4 * 1024 * 1024      # 再大就别往本地模型里塞了
OCR_PROMPT = ('把图上的文字原样读出来，一行一行照抄。'
              '不要解释、不要翻译、不要补充。图上没有字就直说"图上没有字"。')


def _ollama_vision(b64, prompt, timeout=240):
    body = json.dumps({'model': VISION_MODEL, 'stream': False,
                       'messages': [{'role': 'user', 'content': prompt,
                                     'images': [b64]}]}).encode('utf-8')
    req = urllib.request.Request(OLLAMA + '/api/chat', data=body,
                                 headers={'Content-Type': 'application/json'})
    d = json.loads(urllib.request.urlopen(req, timeout=timeout)
                   .read().decode('utf-8', 'ignore'))
    return ((d.get('message') or {}).get('content') or '').strip()


def read_image(url, ask='', max_imgs=6):
    """读图上的字。主力是**本机 RapidOCR**：准、快，长图整张读，不出网不花钱。

    url 可以给一个，也可以给一串（一次读完，省得一张张来回问）。
    带 ask（想问图里的事，不只是抄字）改走 ollama 的 qwen2.5vl:3b 看图答；
    RapidOCR 一行字都没读到时也拿它兜一次底。
    LOFTER 上"文章在图里"的帖子，先用 lofter_post 拿到图片链接，再用这个读。"""
    urls = url if isinstance(url, list) else [url]
    urls = [u.strip() for u in urls if isinstance(u, str) and u.strip()]
    if not urls:
        raise ToolError('没给图片链接')
    urls = urls[:max(1, min(int(max_imgs or 6), 10))]
    ask = (ask or '').strip()

    tmpdir = tempfile.mkdtemp(prefix='lit_ocr_')
    ok = []               # (序号, url, 本地路径)
    out = []
    try:
        for i, u in enumerate(urls, 1):
            try:
                req = urllib.request.Request(u, headers={'User-Agent': UA,
                                                         'Accept-Encoding': 'identity'})
                raw = urllib.request.urlopen(req, timeout=60).read()
            except Exception as e:
                out.append('[%d] %s\n没下载下来：%s' % (i, u[:80], str(e)[:80]))
                continue
            if len(raw) > IMG_MAX_BYTES:
                out.append('[%d] %s\n这张太大（%d 字节），跳过了'
                           % (i, u[:80], len(raw)))
                continue
            ext = os.path.splitext(urllib.parse.urlparse(u).path)[1]
            if not (0 < len(ext) <= 5 and ext[1:].isalnum()):
                ext = '.jpg'
            fp = os.path.join(tmpdir, '%d%s' % (i, ext))
            with open(fp, 'wb') as f:
                f.write(raw)
            ok.append((i, u, fp))

        if ask:                              # 问图：看图模型上场
            for i, u, fp in ok:
                try:
                    with open(fp, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode()
                    txt = _ollama_vision(b64, ask)
                except Exception as e:
                    out.append('[%d] %s\n读失败：%s：%s'
                               % (i, u[:80], type(e).__name__, str(e)[:100]))
                    continue
                out.append('[%d] %s\n%s' % (i, u[:80], txt or '（它没答上来）'))
        else:                                # 读字：RapidOCR 为主，ollama 兜底
            res = _rapid_ocr([fp for _, _, fp in ok])
            for i, u, fp in ok:
                lines = res.get(fp) if res else None
                if lines:
                    out.append('[%d] %s\n%s' % (i, u[:80], '\n'.join(lines)))
                    continue
                try:
                    with open(fp, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode()
                    txt = _ollama_vision(b64, OCR_PROMPT)
                except Exception as e:
                    out.append('[%d] %s\n读失败：%s：%s'
                               % (i, u[:80], type(e).__name__, str(e)[:100]))
                    continue
                note = txt or '（没读出字）'
                if '没有字' in note:
                    note = 'OCR 和看图模型都没读出字——可能真是张没字的图。'
                out.append('[%d] %s\n%s' % (i, u[:80], note))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if not out:
        raise ToolError('一张都没读成')
    return '\n\n'.join(out)


TOOLS = {
    'web_search': {
        'args': 'q（关键词）, n',
        'desc': '上网搜一段。回标题+链接+摘要。摘要是二手的，要引用原文再用 web_fetch。',
        'fn': web_search,
    },
    'web_fetch': {
        'args': 'url',
        'desc': '抓一个网页的正文。搜到结果但要看具体内容时用。',
        'fn': web_fetch,
    },
    'gh_search': {
        'args': 'q, kind（repositories/issues）, n',
        'desc': '搜 GitHub 仓库或 issue。不需要 token。',
        'fn': gh_search,
    },
    'gh_list': {
        'args': 'owner, repo, path, ref',
        'desc': '列 GitHub 仓库的目录。',
        'fn': gh_list,
    },
    'gh_file': {
        'args': 'owner, repo, path, ref',
        'desc': '读 GitHub 上一个文件。',
        'fn': gh_file,
    },
    'find_skill': {
        'args': 'q（关键词，可空）',
        'desc': '找本机装着的 skill / agent（不出网）。想知道这台机器已经会干什么时用。',
        'fn': find_skill,
    },
    'lofter_post': {
        'args': 'url（文章链接，形如 xxx.lofter.com/post/xxx_xxx）',
        'desc': '抓一篇 LOFTER 文章的全文（标题/标签/时间/正文）。不用登录，只拿公开可见的；'
                '这篇要权限或要付费就直说拿不到。',
        'fn': lofter_post,
    },
    'lofter_blog': {
        'args': 'name（博客名或博客链接）, collection_id（可选，给了就列该合集的文章）, limit',
        'desc': '列一个 LOFTER 博客的合集；给了 collection_id 就列合集里的文章。不用登录。'
                '单个合集最多 30 条。**要看一个账号的全部作品，别用这个**——'
                '用 lofter_works。',
        'fn': lofter_blog,
    },
    'lofter_works': {
        'args': 'name（博客名或博客链接）, max_collections（默认 20）, per_collection（默认 100）',
        'desc': '**一个 LOFTER 账号的全部作品清单**：一次调用把它的所有合集都翻一遍，'
                '按合集分组列出标题/日期/链接（含 post_id，拿到就能接着用 lofter_post 抓全文）。'
                '要"整理这个账号的作品""这个号写过什么"就用它，**一次就够，别重复调**'
                '（内部十几个请求、约十几秒）。'
                '⚠️ 结果可能很长（几百篇、两三万字）。**别把整个清单抄进你的回答**——'
                '那样会写到输出上限、被硬生生截断，读者看到的是一张断掉的表。'
                '你只要给概览（几个合集、各多少篇、本人/他人各多少）＋**指路**'
                '（细看哪一篇就说哪一篇），完整清单界面会让她直接放进材料框。'
                '⚠️ 只覆盖归进了合集的文章：没归集的那部分'
                '公开接口看不到（主页作品流和归档页要登录，本工具不登录）。'
                '⚠️ 合集可能混着**别人的**文章（多人合写），那些会标 @作者、链接指回他本人'
                '的博客；要"这个账号的作品"，只取没标 @ 的。',
        'fn': lofter_works,
    },
    'read_image': {
        'args': 'url（图片链接，也可以给一串）, ask（可选，想问别的）, max_imgs',
        'desc': '读**图上的字**。主力是本机 RapidOCR（准、快，长图整张读），'
                '带 ask 可改问图里的事（走 ollama 小模型）。'
                'LOFTER 上"文章在图里"的帖子：先用 lofter_post 拿到图片链接，再用这个读。',
        'fn': read_image,
    },
}


def tool_help():
    return '\n'.join('· %s(%s) —— %s' % (k, v['args'], v['desc']) for k, v in TOOLS.items())


def run(name, args):
    """执行一个工具。失败返回 "（没查到：原因）"，不抛——让模型自己看着办。"""
    t = TOOLS.get((name or '').strip())
    if not t:
        return '（没这个工具：%s。可用的有：%s）' % (name, '、'.join(TOOLS))
    if not isinstance(args, dict):
        return '（参数得是个对象）'
    try:
        return t['fn'](**args)
    except TypeError as e:
        return '（参数不对：%s。%s 要的是：%s）' % (e, name, t['args'])
    except ToolError as e:
        return '（没查到：%s）' % e
    except Exception as e:
        return '（工具出错了：%s：%s）' % (type(e).__name__, str(e)[:150])
