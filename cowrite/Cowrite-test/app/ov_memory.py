# -*- coding: utf-8 -*-
"""伴写系统的持久记忆层（OpenViking 数据面）。

设计取向与 WorkBuddy 自己的记忆模式同构——三层：

  ① 时间节点  memories/sessions/YYYY-MM-DD.md   会话/日，**append-only，永不覆盖**
  ② 任务节点  resources/<作品>/<part>/*.md      作品按 Part 累积，每段一个文件
  ③ 长期      memories/profile.md + preferences/  蒸馏出来的、跨会话有效的判断

读的顺序是**先近后远**：先读当天的会话日志与当前 Part，需要时才回看更早的。
写只做追加；蒸馏是唯一的"改写"动作，且只在明确调用时发生。

零第三方依赖：只用标准库 urllib，和 dsh-伴写 其余部分一致。
鉴权：OpenViking 在 api_key 模式下 **root key 不能碰租户数据**，必须换 user key。
"""
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = 'http://127.0.0.1:1933'
CONF_PATH = os.path.expanduser('~/.openviking/ov.conf')
WS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'workspaces.json')
DEFAULT_WS = 'novel'


def load_workspaces():
    """读工作区注册表。读不到就退回单区（novel），**绝不因为配置缺失就让记忆层挂掉**。"""
    try:
        with open(WS_PATH, encoding='utf-8') as f:
            d = json.load(f)
        return (d.get('workspaces') or {}, d.get('default') or DEFAULT_WS)
    except Exception:
        return ({}, DEFAULT_WS)


def resolve_workspace(name=None):
    """工作区名 → 该区在 OpenViking 里的 user 名。

    **分区做在 user 这一层，不是路径、也不是 tag**，理由写在 workspaces.json 里：
    find() 是按 tag 过滤的，不是按路径过滤的——目录分开了，语义召回照样跨目录串。
    而 tag 过滤一旦漏传就是静默失效。换 user 换的是整棵树的根，索引都分开；
    切错了召回空，空会走 ⊘ 沉默，是安全的失效。

    未知的工作区名一律回落到 default——**不猜、不就近匹配**。
    """
    ws, default = load_workspaces()
    key = (name or default).strip()
    if key in ws:
        return key, (ws[key].get('user') or key)
    return default, (ws.get(default, {}).get('user') or 'maomao')


def list_workspaces():
    ws, default = load_workspaces()
    out = []
    for k in sorted(ws):
        v = ws[k]
        out.append({'id': k, 'label': v.get('label', k), 'desc': v.get('desc', ''),
                    'user': v.get('user', k), 'default': k == default})
    return out


class OVError(RuntimeError):
    pass


class OVStore:
    """一层薄封装：把 viking:// 当文件系统用，但按记忆语义组织。

    `workspace` 给出工作区名（见 workspaces.json），它决定这棵树长在哪个 user 下。
    不传就是默认区——**老代码 `OVStore()` 的行为和改之前一模一样**。
    """

    def __init__(self, base=DEFAULT_BASE, key=None, account='maomao', user=None,
                 workspace=None):
        self.base = base.rstrip('/')
        self.account = account
        if user:
            self.workspace = workspace or DEFAULT_WS
            self.user = user
        else:
            self.workspace, self.user = resolve_workspace(workspace)
        self.root = 'viking://user/%s' % self.user
        self._root_key = key or self._root_key_from_conf()
        self._key = None

    # ── 鉴权 ────────────────────────────────────────────────────────
    @staticmethod
    def _root_key_from_conf():
        with open(CONF_PATH, encoding='utf-8') as f:
            return (json.load(f).get('server') or {}).get('root_api_key') or ''

    def _call(self, method, path, body=None, key=None, timeout=90):
        h = {'Content-Type': 'application/json', 'X-API-Key': key or self._key or self._root_key}
        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8', 'replace'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')
            try:
                msg = (json.loads(body).get('error') or {}).get('message') or body
            except Exception:
                msg = body
            raise OVError('%s %s -> %s %s' % (method, path, e.code, msg[:200]))
        except Exception as e:
            raise OVError('%s %s -> %s %s' % (method, path, type(e).__name__, e))

    def _call_raw(self, method, path, body=None, timeout=300):
        """有些接口（打包）返回二进制流而不是 JSON。"""
        h = {'Content-Type': 'application/json', 'X-API-Key': self._key or self._root_key}
        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise OVError('%s %s -> %s %s' % (method, path, e.code,
                                              e.read().decode('utf-8', 'replace')[:200]))
        except Exception as e:
            raise OVError('%s %s -> %s %s' % (method, path, type(e).__name__, e))

    def _lookup_user_key(self):
        """在账号下找这个 user 的 key；没有返回 None（不抛）。"""
        r = self._call('GET', '/api/v1/admin/accounts/%s/users' % self.account,
                       key=self._root_key)
        for u in (r.get('result') or []):
            if u.get('user_id') == self.user and u.get('api_key'):
                self._key = u['api_key']
                return self._key
        return None

    def login(self):
        """建账号（幂等）+ 建 user（幂等），取回 user key。root key 不能访问数据面。

        v3.9 起工作区是 user，所以**新工作区的 user 可能还不存在**，这里要能建：
        `POST /api/v1/admin/accounts/{account}/users {user_id, role}`。

        建不出来就报一个说得清的错，**绝不静默退回别的区**——退回别的区等于
        写到了别的地方，而**写错地方比写不进去危险得多**：写不进去你会看见报错，
        写到小说区的拆文笔记，要等某天伴写忽然冒出一句怪话才被发现。
        """
        try:
            self._call('POST', '/api/v1/admin/accounts',
                       {'account_id': self.account, 'admin_user_id': self.user},
                       key=self._root_key)
        except OVError as e:
            if 'already exists' not in str(e):
                raise
        if self._lookup_user_key():
            return self._key
        # 这个 user 还不存在——说明这是个新建的工作区，建它。
        try:
            self._call('POST', '/api/v1/admin/accounts/%s/users' % self.account,
                       {'user_id': self.user, 'role': 'user'}, key=self._root_key)
        except OVError as e:
            if 'exist' not in str(e).lower():
                raise OVError('工作区「%s」（user=%s）建不出来：%s'
                              % (self.workspace, self.user, e))
        if self._lookup_user_key():
            return self._key
        raise OVError('没取到 user key：工作区「%s」/ user=%s'
                      % (self.workspace, self.user))

    # ── 基础设施 ────────────────────────────────────────────────────
    def mkdir(self, uri, description=None):
        try:
            return self._call('POST', '/api/v1/fs/mkdir',
                              {'uri': uri, 'description': description})
        except OVError as e:
            if 'already exists' in str(e) or 'CONFLICT' in str(e):
                return {'status': 'exists', 'uri': uri}
            raise

    def ls(self, uri):
        return (self._call('GET', '/api/v1/fs/ls?uri=' + urllib.parse.quote(uri))
                .get('result') or [])

    def rm(self, uri, recursive=True):
        """删掉一个 uri。删目录必须 recursive=True，否则服务端报 412。

        维护用，不是日常路径——日常只追加。注意两点：
        写是异步的，刚 write 完立刻 rm 可能撞上它的写入锁（实测报 409 lock），
        重试即可；`ls` 也要等一会才反映得出来。
        """
        q = urllib.parse.urlencode({'uri': uri, 'recursive': 'true' if recursive else 'false'})
        return self._call('DELETE', '/api/v1/fs?' + q)

    def read(self, uri):
        """返回正文文本。服务端可能把 result 给成字符串，也可能是 {content: …}。"""
        r = self._call('GET', '/api/v1/content/read?uri=' + urllib.parse.quote(uri))
        res = r.get('result')
        if isinstance(res, str):
            return res
        if isinstance(res, dict):
            return res.get('content') or res.get('text') or ''
        return ''

    def read_body(self, uri):
        """读**正文**，剥掉 OpenViking 加的那段 YAML 头。

        服务端读文件时会在前面补一段 `---\\ndirectory: …\\ngenerated_by: …\\n---\\n\\n`。
        那是它的元数据，不是我们写的东西——直接拿去当提示词会把一堆 YAML 灌进模型，
        而且 `append_session` 的「读旧的 + 写回去」会把这段头一遍遍叠进日志里。
        """
        return self._strip_front_matter(self.read(uri))

    @staticmethod
    def _strip_front_matter(text):
        t = text or ''
        if t.startswith('---'):
            end = t.find('\n---', 3)
            if end != -1:
                t = t[end + 4:]
        return t.lstrip('\n')

    def write(self, uri, content, tags=None, mode='replace'):
        body = {'uri': uri, 'content': content, 'mode': mode, 'wait': True}
        if tags:
            body['tags'] = tags          # 必须严格 k=v
            body['tag_mode'] = 'replace'
        return self._call('POST', '/api/v1/content/write', body)

    # ── 命名空间 ────────────────────────────────────────────────────
    def ensure_tree(self, work):
        for u in ['%s/resources/' % self.root,
                  '%s/resources/%s/' % (self.root, work),
                  '%s/memories/' % self.root,
                  '%s/memories/sessions/' % self.root,
                  '%s/memories/preferences/' % self.root]:
            self.mkdir(u)

    # ── 任务节点：作品 / Part ───────────────────────────────────────
    def write_segment(self, work, part, seg_id, text, tags=None, day=None):
        uri = '%s/resources/%s/%s/%s.md' % (self.root, work, part, seg_id)
        t = ['kind=seg', 'work=%s' % work, 'part=%s' % part]
        if day:
            t.append('day=%s' % day)
        t += list(tags or [])
        return self.write(uri, text, t)

    def write_overview(self, work, part, text):
        """自制的五栏剖面。写在 .overview.md 上——OpenViking 只拿它当索引，
        不会用它配的 vlm 覆盖（见 concepts/03-context-layers.md「写保护」）。"""
        uri = '%s/resources/%s/%s/.overview.md' % (self.root, work, part)
        return self.write(uri, text, ['kind=overview', 'work=%s' % work, 'part=%s' % part])

    # ── 时间节点：会话 / 日 ─────────────────────────────────────────
    def append_session(self, day, text):
        """append-only。同一天多次调用只追加，不覆盖。

        两个坑都在这里堵掉：
        ① **只读正文**（`read_body`），否则会把 OpenViking 的 YAML 头一遍遍叠进日志；
        ② **同样的内容不重复写**——写完立刻读，读到的可能是旧版本（写入是异步的），
           于是"读旧的 + 写回去"会把已经写过的条目再抄一遍（实测日志里出现过三条重复）。
           所以先查一遍：这段文字已经在里面了就什么都不做。
        """
        uri = '%s/memories/sessions/%s.md' % (self.root, day)
        old = ''
        try:
            old = self.read_body(uri) or ''
        except OVError:
            pass
        body = (text or '').strip()
        if body and body in old:
            return {'status': 'skipped', 'uri': uri}
        head = '# %s 写作日志\n\n' % day if not old else old.rstrip() + '\n\n'
        return self.write(uri, head + body + '\n',
                          ['kind=session', 'day=%s' % day])

    def dedupe_session(self, day):
        """把某天日志里的重复段落去掉（保持原有顺序），返回 (保留条数, 去掉条数)。

        这是**维护动作**，不是常规路径。`append_session` 已经会跳过完全相同的
        一段，所以新写入不会再造重复；但更早之前（去重还没加上时）写进去的
        重复会一直留在文件里——append-only 意味着它不会自己变干净。
        日志被污染过一次就调一次这个。空日志返回 (0, 0)，不抛。
        """
        uri = '%s/memories/sessions/%s.md' % (self.root, day)
        try:
            old = self.read_body(uri) or ''
        except OVError:
            return (0, 0)
        seen, kept = set(), []
        for para in old.split('\n\n'):
            p = para.strip()
            if not p:
                continue
            if p in seen:
                continue
            seen.add(p)
            kept.append(p)
        if len(kept) == len([p for p in old.split('\n\n') if p.strip()]):
            return (len(kept), 0)
        self.write(uri, '\n\n'.join(kept) + '\n', ['kind=session', 'day=%s' % day])
        return (len(kept), len([p for p in old.split('\n\n') if p.strip()]) - len(kept))

    # ── 长期 ────────────────────────────────────────────────────────
    def write_profile(self, text):
        return self.write('%s/memories/profile.md' % self.root, text, ['kind=profile'])

    def write_preference(self, kind, text):
        return self.write('%s/memories/preferences/%s.md' % (self.root, kind),
                          text, ['kind=preference', 'pref=%s' % kind])

    # ── 检索：先近后远 ──────────────────────────────────────────────
    def find(self, query='', work=None, part=None, day=None, kind=None,
             limit=5, node_limit=None):
        tags = []
        if work:
            tags.append('work=%s' % work)
        if part:
            tags.append('part=%s' % part)
        if day:
            tags.append('day=%s' % day)
        if kind:
            tags.append('kind=%s' % kind)
        body = {'query': query, 'limit': limit}
        if tags:
            body['tags'] = tags
        if node_limit:
            body['node_limit'] = node_limit
        r = self._call('POST', '/api/v1/search/find', body)
        res = r.get('result') or {}
        out = []
        for bucket in ('memories', 'resources', 'skills'):
            for it in (res.get(bucket) or []):
                out.append({'bucket': bucket, 'uri': it.get('uri'),
                            'level': it.get('level'), 'score': it.get('score'),
                            'abstract': it.get('abstract') or ''})
        return out

    def recent_sessions(self, days=3):
        r = self.find(kind='session', limit=days)
        return r

    def recent_session_texts(self, days=2, max_chars=1200):
        """最近几天的会话正文（**时间节点**），按**从近到远**返回 [(day, text)]。

        为什么直接按日读而不走 find：日文件的名字就是日期，"最近"这个顺序是确定的；
        走 find 的话排序取决于相关度，最近的那条不一定排在最前——
        而"先近后远"是这套记忆的第一条规矩，不能交给相关度去碰运气。
        读不到就是没有，返回空列表，不抛。
        """
        out = []
        for i in range(days):
            d = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
            try:
                t = (self.read('%s/memories/sessions/%s.md' % (self.root, d)) or '').strip()
            except OVError:
                t = ''
            if t:
                # 太长只留尾巴——最近发生的事在后面
                out.append((d, t[-max_chars:] if len(t) > max_chars else t))
        return out

    # ── 装配给模型看的记忆块 ────────────────────────────────────────
    PRINCIPLE = (
        '【记忆须知】\n'
        '你面前有一份你自己旧的观察，它不是新输入，是你上一次留下的。分三层：\n'
        '最近的写作日志（最贴当下）／这份作品已建起来的东西（按需取）／'
        '长期判断（很短，每次都看）。\n'
        '三条规矩：一、记忆是旧观察，不是这段话的一部分——'
        '与当前句冲突时以当前句为准，绝不在搭话里复述记忆内容；\n'
        '二、先近后远、按需展开，不要为了解全局把记忆读一遍——'
        '对未完成的作品，读全了反而会把它当已完成的东西看；\n'
        '三、写记忆只追加、不改写，只有被明确要求整理（蒸馏）时才压缩改写。\n'
        '你没有读过全文——这是设计，不是缺陷。记忆里没有的东西，'
        '正确动作是承认不知道或沉默（⊘），不是拿记忆当线索去补全。'
    )

    def memory_block(self, current_text, work=None, part=None, limit=5):
        """按「先近后远」装配注入块。检索为空是合法状态，此时如实说明。"""
        lines = [self.PRINCIPLE, '']

        longterm = []
        for it in self.find(kind='profile', limit=2):
            try:
                body = self.read(it['uri']).strip()
            except OVError:
                body = ''
            if body:
                longterm.append(body)
        for it in self.find(kind='preference', limit=6):
            try:
                body = self.read(it['uri']).strip()
            except OVError:
                body = ''
            if body:
                longterm.append(body)
        if longterm:
            lines.append('【长期判断】')
            lines += longterm
            lines.append('')

        # 最近几次的伴写（时间节点）——"历史伴写文本"就是从这里回来的。
        # PRINCIPLE 里承诺了"最近的写作日志（最贴当下）"，这里把它兑现。
        recent = self.recent_session_texts()
        if recent:
            lines.append('【最近几次的伴写 — 你自己说过的话，不是她刚写的】')
            for d, t in recent:
                lines.append('— %s —' % d)
                lines.append(t)
            lines.append('')
        else:
            lines.append('【最近几次的伴写】（无。这是第一次，或日志还没写下来。）')
            lines.append('')

        hits = self.find(current_text, work=work, part=part, limit=limit)
        lines.append('【本次召回】')
        if hits:
            for h in hits[:limit]:
                name = h['uri'].split('/')[-1]
                lines.append('- %s（level %s，score %s）' %
                             (name, h['level'], round(h['score'] or 0, 3)))
        else:
            lines.append('（无。不要凭记忆编内容。）')
        lines.append('')
        lines.append('以上是你自己旧的观察，不是她刚写的内容，不要念出来；'
                     '只允许当作"位置事实"使用。')
        return '\n'.join(lines)

    # ── 打包 ────────────────────────────────────────────────────────
    def export_bundle(self, uri, out_path=None, include_vectors=True):
        """.ovpack：整棵子树导出成一个包，可归档 / 搬机器 / 交给别人。

        返回 (bytes, 落盘路径或 None)。
        """
        blob = self._call_raw('POST', '/api/v1/pack/export',
                              {'uri': uri, 'include_vectors': include_vectors})
        if out_path:
            with open(out_path, 'wb') as f:
                f.write(blob)
        return blob, out_path
