# -*- coding: utf-8 -*-
"""模型后端适配层：一套伴写策略，接哪家模型都行。

默认仍是 dots3-note-prev，但可以在网页上换成别家。

── 为什么自己写，而不是接 LiteLLM 那类统一层 ────────────────────
通用聊天前端（Open WebUI 那一类）遇到非 OpenAI 格式就建议再跑一个
LiteLLM 做协议翻译。我们不这么做，两个理由：

1. **我们只有两种格式**。OpenAI 的 /chat/completions 和 Anthropic 的
   /v1/messages 覆盖了要用到的全部端点（含本地 Ollama、Moonshot、智谱、
   通义——它们都自称 OpenAI 兼容）。为两种格式再叠一个服务、一个容器、
   一层故障点，不划算。
2. **伴写不是通用聊天**。它只有一个调用形状：system + user → 一段正文。
   不需要 tool calling、不需要流式、不需要 embeddings。通用层带来的
   绝大多数能力在这儿是死重量。

   （后来文学工作台要"多轮 + 会自己找资料"，是在这一层**之上**加的：
   多轮走下面的 chat_messages()，工具走 lit_tools.py 的标签协议。
   本层仍然只管"把一段话说出去、把一段正文拿回来"，不认得工具。）

所以这里是**薄薄一层**：一张 provider 表 + 一个 chat() + 一个 probe()。
多一种协议就改一个文件，不动 server.py。

── 边界：能选什么，不能选什么 ────────────────────────────────
能选：**用哪家模型**（provider + model + 端点）。
不能选：temperature、thinking、max_tokens —— 这些由 v3 的策略参数定，
在 `v3/params.json` 的 `sampling` 里（temperature 0.3、top_p 1.0、
max_tokens 2048、thinking "disabled"）。这不是偷懒：
那两个值是伴写质量与实验可复现的前提，交给使用者随手调，
论文里那些对照就都不成立了。要调请改 `v3/params.json` 并在日志里留痕。

零第三方依赖：只用标准库 urllib，与项目其余部分一致。
"""
import json
import os
import urllib.error
import urllib.request

# ---------------------------------------------------------------- provider 表
# 每个条目声明"它说的是哪种协议"，而不是"它是什么模型"。
# 换 provider 只改这里；server.py 不需要知道协议细节。
PROVIDERS = [
    {
        'id': 'dots3',
        'label': 'dots3-note-prev（默认）',
        'api': 'anthropic-messages',
        'base_url': 'http://<API_HOST>',
        'model': 'dots3-note-prev',
        'key_env': 'DOTS3_API_KEY',
        # dots3-note-prev 的可用上下文比其他 provider 更紧。这里不是“猜 token”，
        # 而是给上层一个可执行的分块预算：超过就分片处理，绝不硬砍。
        'input_chars': 12000,
        # 单轮输出也留出上下文余量；总长度由 chat_messages_complete 续写补齐。
        'output_chunk_tokens': 4096,
        'continuation_rounds': 4,
        'hint': '论文实验所用的模型；端点在内网，只有本机可达。',
    },
    {
        'id': 'deepseek',
        'label': 'DeepSeek',
        'api': 'openai-completions',
        'base_url': 'https://api.deepseek.com',
        'model': 'deepseek-chat',
        'key_env': 'DEEPSEEK_API_KEY',
        'hint': 'DeepSeek 官方端点。',
    },
    {
        'id': 'openai',
        'label': 'OpenAI',
        'api': 'openai-completions',
        'base_url': 'https://api.openai.com/v1',
        'model': 'gpt-4o-mini',
        'key_env': 'OPENAI_API_KEY',
        'hint': 'OpenAI 官方；也适用于多数 OpenAI 兼容网关。',
    },
    {
        'id': 'anthropic',
        'label': 'Anthropic Claude',
        'api': 'anthropic-messages',
        'base_url': 'https://api.anthropic.com',
        'model': 'claude-sonnet-4-5',
        'key_env': 'ANTHROPIC_API_KEY',
        'hint': 'Anthropic 官方。注意它不支持 thinking 字段的关闭语义，'
                '本层会照发 {type: disabled}，多数情况下被忽略。',
    },
    {
        'id': 'moonshot',
        'label': 'Moonshot（月之暗面）',
        'api': 'openai-completions',
        'base_url': 'https://api.moonshot.cn/v1',
        'model': 'moonshot-v1-8k',
        'key_env': 'MOONSHOT_API_KEY',
        'hint': 'OpenAI 兼容。',
    },
    {
        'id': 'zhipu',
        'label': '智谱 GLM',
        'api': 'openai-completions',
        'base_url': 'https://open.bigmodel.cn/api/paas/v4',
        'model': 'glm-4-flash',
        'key_env': 'ZHIPU_API_KEY',
        'hint': 'OpenAI 兼容。',
    },
    {
        'id': 'ollama',
        'label': '本地 Ollama',
        'api': 'openai-completions',
        'base_url': 'http://127.0.0.1:11434/v1',
        'model': 'qwen2.5:7b',
        'key_env': '',
        'hint': '本机跑，不出网。Ollama 不校验 key，但要填个非空字符串'
                '（本层会自动补 "ollama"）。',
    },
    {
        'id': 'custom-openai',
        'label': '自定义 · OpenAI 兼容',
        'api': 'openai-completions',
        'base_url': '',
        'model': '',
        'key_env': '',
        'hint': '任何说 /chat/completions 的端点：vLLM、One-API、'
                'LM Studio、公司内网网关都算。',
    },
    {
        'id': 'custom-anthropic',
        'label': '自定义 · Anthropic 兼容',
        'api': 'anthropic-messages',
        'base_url': '',
        'model': '',
        'key_env': '',
        'hint': '说 /v1/messages 的端点。',
    },
]

_BY_ID = {p['id']: p for p in PROVIDERS}
DEFAULT_ID = 'dots3'


def list_providers():
    """给前端列下拉用。**不含任何 key**。"""
    return [{'id': p['id'], 'label': p['label'], 'api': p['api'],
             'base_url': p['base_url'], 'model': p['model'],
             'key_env': p['key_env'], 'hint': p['hint']} for p in PROVIDERS]


class ProviderError(RuntimeError):
    """端点连不上、鉴权失败、返回结构不对——这些是**故障**。"""


class EmptyReplyError(ProviderError):
    """连上了、也回了，但正文是空的——这**不是故障**，是"这次没有"。

    单独分出来，是因为伴写系统里两者命运不同：
    故障交给上层报错，空回复要变成一张 ⊘ 卡片（工作流的第 5 步：
    主动声明沉默）。把"没有可说的"当成报错弹窗，就丢掉了这个设计里
    最要紧的一条——**沉默是一等输出**。
    """


# ---------------------------------------------------------------- 解析
def resolve(cfg):
    """把 config.json 那种稀疏配置补全成一份可以直接用的配置。

    **向后兼容是硬要求**：老配置里只有 base_url / api_key / model / api
    四项、没有 provider 字段。那种配置进来，出来的行为必须和改动前
    一模一样——所以 provider 缺失时走"自定义"路径，不套任何预设默认值。

    key 的优先顺序：config.json 里写了就用它；没写则去环境变量找。
    """
    out = dict(cfg or {})
    pid = out.get('provider') or ''
    if pid and pid in _BY_ID:
        pre = _BY_ID[pid]
        out['provider'] = pid
        out['api'] = out.get('api') or pre['api']
        out.setdefault('base_url', '')
        out['base_url'] = out.get('base_url') or pre['base_url']
        out['model'] = out.get('model') or pre['model']
        if out.get('input_chars') is None and pre.get('input_chars'):
            out['input_chars'] = pre['input_chars']
        if out.get('continuation_rounds') is None and pre.get('continuation_rounds'):
            out['continuation_rounds'] = pre['continuation_rounds']
        if out.get('output_chunk_tokens') is None and pre.get('output_chunk_tokens'):
            out['output_chunk_tokens'] = pre['output_chunk_tokens']
        if not out.get('api_key') and pre.get('key_env'):
            out['api_key'] = os.environ.get(pre['key_env'], '') or ''
    else:
        # 老配置 / 自定义：不动它的四个字段，只补 api 默认值
        out['provider'] = pid or _guess_id(out)
        out['api'] = out.get('api') or 'openai-completions'
        out['base_url'] = out.get('base_url', '')
        out['model'] = out.get('model', '')
    if not out.get('api_key') and out['provider'] == 'ollama':
        out['api_key'] = 'ollama'          # 不校验，但不能为空
    return out


def _guess_id(cfg):
    """老配置没有 provider 字段时，按端点猜一个，只为显示得好看点。"""
    if 'note3-prev-api' in (cfg.get('base_url') or ''):
        return 'dots3'
    return 'custom-openai' if cfg.get('api', 'openai-completions') == 'openai-completions' \
        else 'custom-anthropic'


def configured(cfg):
    """能不能真的发请求——等价于 server.online()。"""
    c = resolve(cfg)
    return bool(c.get('api_key')) and bool(c.get('base_url'))


def input_budget(cfg, default=90000):
    """单次请求可放入的字符预算。

    消费方必须用它**分片**，不能拿它当截断刀：
    dots3-note-prev 的上下文比通用 provider 紧，60000 字直接送过去时，
    上游会截输入或把输出压到极短；先分片再回答才是完整链路。
    """
    c = resolve(cfg)
    try:
        n = int(c.get('input_chars') or default)
    except Exception:
        n = int(default)
    return max(4000, n)


def continuation_rounds(cfg, default=0):
    """输出被 max_tokens 截断后最多自动续写几轮。"""
    c = resolve(cfg)
    try:
        n = int(c.get('continuation_rounds') if c.get('continuation_rounds') is not None
                else default)
    except Exception:
        n = int(default)
    return max(0, min(8, n))


def output_budget(cfg, desired):
    """单轮输出 token 上限。

    dots3 这类端点同时受输入/输出上下文限制；把长回答拆成多轮续写，
    比单轮把上下文挤爆更可靠。其他 provider 原样返回调用方要的上限。
    """
    c = resolve(cfg)
    try:
        want = max(1, int(desired))
    except Exception:
        want = 2048
    cap = c.get('output_chunk_tokens')
    if cap is None:
        return want
    try:
        return min(want, max(1, int(cap)))
    except Exception:
        return want


def mask_key(k):
    """给前端显示用的打码 key，别把整串密钥送进浏览器。"""
    k = k or ''
    if not k:
        return ''
    return (k[:4] + '…' + k[-4:]) if len(k) > 10 else '••••'


# ---------------------------------------------------------------- 调用
# ── 上一句话是怎么停的 ────────────────────────────────────────────
# 起因（2026-09-19 实测）：让她"整理这个账号的作品"，模型列了 288 行表格，
# 写到 6633 字时被 `max_tokens` 从中间**硬生生切断**——表断在半行上。
# 以前这个信息只在"正文一个字都没有"时才被读（见 `_chat_anthropic`），
# 于是**有正文、但被截断**这种情况完全看不见：交出去的东西看起来是完整的。
# 所以把停因留下来，让调用方（文学栏收口时）能把它说出来。
# 不做成返回值：那要把 `chat` / `chat_messages` 的返回契约改掉，
# 而它们有一堆调用点（伴写卡片、剖面、重写）。留一个只读的"上一句"最轻。
_LAST_STOP = {'reason': ''}


def last_stop():
    """上一次调用的停因（`max_tokens` = 被输出上限截断，`end_turn` = 自然收笔）。"""
    return dict(_LAST_STOP)


def chat(cfg, system, user, temperature=0.3, max_tokens=2048,
         timeout=180, thinking='disabled'):
    """单轮入口：system + user → 一段正文。

    所有调用点（伴写卡片、全文剖面、重写）都必须走这里。
    以前每个调用点各写一遍 if/else 判格式，抄第二遍的时候就漏过一次
    （剖面那边拼成 /chat/completions 而配置是 anthropic，404）。
    **格式判断只在这一个地方做。**

    失败抛 ProviderError，消息尽量说人话（端点、状态码、服务端给的提示）。
    """
    return chat_messages(cfg, [{'role': 'user', 'content': user}], system=system,
                         temperature=temperature, max_tokens=max_tokens,
                         timeout=timeout, thinking=thinking)


def chat_messages(cfg, messages, system='', temperature=0.3, max_tokens=2048,
                  timeout=180, thinking='disabled'):
    """多轮入口：messages 是 [{'role': 'user'|'assistant', 'content': str}]。

    文学工作台的对话和它的工具回喂都需要多轮——模型不可能只看得见最后一句。
    **没有把它做成另一个入口**：单轮的 chat() 现在只是它的一层壳，
    协议分支仍然只在这一个函数里，不新增第二处判断。

    system 单独传而不是混进 messages，是因为 Anthropic 把它放在顶层字段里，
    OpenAI 则把它当一条 system 消息——**这个差异只在这里消化一次**。
    """
    c = resolve(cfg)
    fmt = c.get('api', 'openai-completions')
    if not c.get('base_url'):
        raise ProviderError('没填端点地址（base_url）')
    if not c.get('api_key'):
        raise ProviderError('没填 API Key')

    msgs = _norm_messages(messages)
    _LAST_STOP['reason'] = ''      # 上一次的停因不许漏给这一次

    if fmt == 'anthropic-messages':
        return _chat_anthropic(c, msgs, system, temperature, max_tokens,
                               timeout, thinking)
    return _chat_openai(c, msgs, system, temperature, max_tokens, timeout)


_CONTINUE_PROMPT = (
    '上一条回答刚才在输出上限处中断了。请从最后一个字符后面继续，'
    '只输出后续内容。不要重复任何已经写过的句子、列表项或标题，'
    '不要重新开头，不要解释。如果确实已经完整，只输出 <<COWRITE_END>>。'
)
_CONTINUE_END = '<<COWRITE_END>>'


def chat_messages_complete(cfg, messages, system='', temperature=0.3,
                           max_tokens=2048, timeout=180, thinking='disabled',
                           max_rounds=None):
    """完整多轮回答：被 output limit 截断时自动从断点续写。

    续写时保留原 messages，并在其后追加“已输出的半截 + 只接着写”的指令。
    返回值只包含正文，不含续写控制语；`last_stop()` 仍报告最后一次调用的停因。
    默认只对 providers 表里声明了 `continuation_rounds` 的模型启用，其他模型
    传 max_rounds=0 即保持旧行为。
    """
    rounds = continuation_rounds(cfg) if max_rounds is None else max(0, int(max_rounds))
    work = list(messages or [])
    parts = []
    for i in range(rounds + 1):
        try:
            piece = chat_messages(cfg, work, system=system, temperature=temperature,
                                  max_tokens=max_tokens, timeout=timeout,
                                  thinking=thinking) or ''
        except EmptyReplyError:
            if parts:
                # 已经拿到半截正文；续写轮没有新内容时保留正文，不把完整结果
                # 倒退成一次故障。停因保留为 max_tokens，调用方仍能看到截断。
                _LAST_STOP['reason'] = 'max_tokens'
                break
            raise
        if i:
            piece = piece.replace(_CONTINUE_END, '').strip()
        if piece:
            parts.append(piece)
        if last_stop().get('reason') != 'max_tokens' or i >= rounds:
            break
        work = work + [
            {'role': 'assistant', 'content': (parts[-1] if parts else '')},
            {'role': 'user', 'content': _CONTINUE_PROMPT},
        ]
    return ''.join(parts)


def _norm_messages(messages):
    """清一遍 messages：丢掉空的、合并相邻同角色的。

    Anthropic 端不接受连续两条同 role（会 400），而工具回喂那一轮很容易
    连着塞两条 user 进去。所以在这里**一次消化掉**，不让调用方各自记得合并。
    """
    out = []
    for m in (messages or []):
        if not isinstance(m, dict):
            continue
        role = (m.get('role') or '').strip()
        content = (m.get('content') or '')
        if not isinstance(content, str):
            content = str(content)
        if role not in ('user', 'assistant') or not content.strip():
            continue
        if out and out[-1]['role'] == role:
            out[-1]['content'] += '\n\n' + content
        else:
            out.append({'role': role, 'content': content})
    if not out:
        raise ProviderError('没有可发送的内容（messages 是空的）')
    # Anthropic 要求第一条必须是 user
    if out[0]['role'] != 'user':
        out.insert(0, {'role': 'user', 'content': '（继续）'})
    return out


def _post(url, payload, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'),
                                 headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')
        try:
            msg = (json.loads(body).get('error') or {}).get('message') or body
        except Exception:
            msg = body
        raise ProviderError('%s → HTTP %s：%s' % (url, e.code, msg[:300]))
    except Exception as e:
        raise ProviderError('%s → %s：%s' % (url, type(e).__name__, e))


def _chat_anthropic(c, messages, system, temperature, max_tokens, timeout, thinking):
    payload = {
        'model': c.get('model'),
        'messages': messages,
        'max_tokens': int(max_tokens or 2048),
        'temperature': temperature,
    }
    if system:
        payload['system'] = system      # 顶层字段，不能混进 messages
    if str(thinking or 'disabled').lower() != 'enabled':
        # 思考块会把 max_tokens 吃光导致正文为空，延迟也翻几倍。
        payload['thinking'] = {'type': 'disabled'}
    data = _post(c['base_url'].rstrip('/') + '/v1/messages', payload, {
        'Content-Type': 'application/json',
        'x-api-key': c.get('api_key', ''),
        'anthropic-version': '2023-06-01',
    }, timeout)
    text = ''.join(b.get('text', '') for b in data.get('content', [])
                   if b.get('type') == 'text')
    _LAST_STOP['reason'] = data.get('stop_reason') or ''
    if not text.strip():
        why = ('模型输出被 max_tokens 截断（思考块占满）'
               if data.get('stop_reason') == 'max_tokens' else '模型未返回正文')
        raise EmptyReplyError(why)
    return text


def _chat_openai(c, messages, system, temperature, max_tokens, timeout):
    payload = {
        'model': c.get('model'),
        # system goes into first message, not a separate field
        'messages': ([{'role': 'system', 'content': system}] if system else []) + messages,
        'temperature': temperature,
    }
    if max_tokens:
        payload['max_tokens'] = int(max_tokens)
    # LongCat official API: default thinking fills reasoning_content and leaves
    # content empty. Companion feel needs content, so disable thinking.
    if 'longcat.chat' in (c.get('base_url') or ''):
        payload['thinking'] = {'type': 'disabled'}
    data = _post(c['base_url'].rstrip('/') + '/chat/completions', payload, {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + c.get('api_key', ''),
    }, timeout)
    try:
        ch = data['choices'][0]
    except Exception:
        raise ProviderError('返回里没有 choices[0].message.content：%s'
                            % json.dumps(data, ensure_ascii=False)[:200])
    # OpenAI stop reason length maps to anthropic max_tokens.
    _LAST_STOP['reason'] = ('max_tokens' if ch.get('finish_reason') == 'length'
                            else (ch.get('finish_reason') or ''))
    try:
        msg = ch.get('message') or {}
        content = msg.get('content') or ''
        if not content:
            content = msg.get('reasoning_content') or ''
        return content
    except Exception:
        raise ProviderError('返回里没有 choices[0].message.content：%s'
                            % json.dumps(data, ensure_ascii=False)[:200])


# ---------------------------------------------------------------- 探活
def probe(cfg, timeout=25):
    """拿最小代价确认"这套配置能不能用"。

    返回 (True, 摘要) / (False, 原因)。给网页上"测试连接"按钮用——
    换完 provider 立刻知道是填错了还是网络不通，
    而不是等到第一次伴写时才蹦出一句看不懂的报错。
    """
    try:
        c = resolve(cfg)
    except Exception as e:
        return (False, '配置有问题：%s' % e)
    if not c.get('base_url'):
        return (False, '没填端点地址')
    if not c.get('api_key'):
        env = _BY_ID.get(c.get('provider'), {}).get('key_env')
        return (False, '没填 API Key' + ('（也可以设环境变量 %s）' % env if env else ''))
    try:
        text = chat(cfg, '你是连通性测试。', '只回复两个字：正常',
                    temperature=0, max_tokens=16, timeout=timeout)
    except ProviderError as e:
        return (False, str(e))
    except Exception as e:
        return (False, '%s：%s' % (type(e).__name__, e))
    return (True, '通。%s @ %s 回复：%s'
            % (c.get('model'), c.get('provider'), (text or '').strip()[:20]))
