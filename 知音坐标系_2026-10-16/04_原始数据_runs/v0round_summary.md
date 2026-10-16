# Localization smoke run summary

- timestamp: 2026-10-15 01:03:33 CST
- provider: dots3
- model: dots3-note-prev
- masked_key: ak_P…pqQT
- probe_ok: True
- probe_detail: 通。dots3-note-prev @ dots3 回复：正常
- theory: generate≠commit; anchors≠tree content; S3 CLOSED; smoke only

## Per-anchor

### A01_transform
- gold: S03_allegorical_transform, S16_ban_psychologize
- bare mapped: ['(unmapped)']
- bare raw (trunc): STOPS: 形态转换; 结构性沟通 RATIONALE: 段落强调沟通失败时主体形态的根本转变，并指出此转变应被视为结构操作而非情绪反应，故“形态转换”与“结构性沟通”可作为定位其现代主义沟通观的两个概念停靠点。
- tree proposed: ['S03_allegorical_transform', 'S16_ban_psychologize'] (on_trunk=True)
- tree rationale: 锚段强调‘形态转换’作为结构操作，并明确禁止将其还原为心理化解释；S03 定义化形/变形寓言为结构操作，S16 为对应禁枝，二者构成定位与约束的完整对齐。

### A02_special_solution
- gold: S07_special_solution
- bare mapped: ['(unmapped)']
- bare raw (trunc): STOPS: 情境性解药; 语境依赖性洞见   RATIONALE: 该段落强调一个仅在特定对话情境中有效的解决方案，其价值高度依赖当下语境，不可泛化，因此“情境性解药”与“语境依赖性洞见”能准确捕捉其临时有效性与不可推广性的双重特征。
- tree proposed: ['S07_special_solution', 'S16_ban_psychologize'] (on_trunk=True)
- tree rationale: 锚段描述了一个仅在特定约束下成立、不可泛化的‘解’，直接对应 S07_special_solution（特解/局部解）；同时警示不可将其误用为普适公式或进行心理化还原，故搭配禁枝 S16_ban_psychologize 以标定边界。

### A03_existential_plain
- gold: S05_existential_plain, S19_existential_horizon
- bare mapped: ['(unmapped)']
- bare raw (trunc): STOPS: 无根基的暴露; 选择的平原感   RATIONALE: 段落聚焦于对话中因缺乏根基而被迫暴露选择的结构性困境，"平原感"作为处境隐喻，指向现代沟通中意义的空旷与无遮蔽。
- tree proposed: ['S05_existential_plain', 'S19_existential_horizon'] (on_trunk=True)
- tree rationale: 锚段落明确描绘「没有遮蔽的开阔地」「选择与无根基」，直接对应 S05 存在主义平原的「开阔无庇护的地平线感：选择与虚无同在」；同时 S19 存在主义地平线提供「选择、责任与无根基处境」的互指层，形成结构—存在双重停靠。

### A04_fractal_horror
- gold: S06_fractal_horror
- bare mapped: ['(unmapped)']
- bare raw (trunc): STOPS: 结构重复; 尺度不变性   RATIONALE: 段落指出日常中存在跨尺度的同构重复，揭示恐惧源于结构而非具体事件，适合用“结构重复”与“尺度不变性”定位其现代主义对系统性异化的关注。
- tree proposed: ['S06_fractal_horror', 'S09_silence_gap'] (on_trunk=True)
- tree rationale: 锚段落描述‘放大一格仍是同构’与‘恐惧来自结构而非事件’，直接命中 S06（分形恐怖：同构细节在每一尺度复现）；同时‘细看每一段日常’暗示对未言说之层的凝视，可停靠于 S09（沉默与空隙：未说出的层是结构的一部分）。二者均为 stop 层，符合优先规则。

### A05_interpretive_vs_plot
- gold: S12_interpretive_vs_plot, S17_ban_plot_reduce
- bare mapped: ['(unmapped)']
- bare raw (trunc): STOPS: 阐释停靠; 情节还原   RATIONALE: 区分“追问事件后续”与“追问意义锚点”两种阅读姿态，揭示将后者强行转化为前者即为对文本多义性的压制。
- tree proposed: ['S12_interpretive_vs_plot', 'S17_ban_plot_reduce'] (on_trunk=True)
- tree rationale: 锚段明确区分‘事件链追问’与‘阐释停靠追问’，并指出将后者强行改写为前者即为情节还原。S12 提供阐释性与情节性的对照停靠层，S17 直接标定该禁枝，二者共同覆盖锚段的对照与禁止逻辑。

## Does / does not prove

- Proves (weak): scripts can dual-arm localize onto an explicit trunk.
- Does NOT prove: understanding achieved; VERIFY main-table gains; agent memory/skills fitting.
- Commit: none — proposals only (`needs_author_commit: true`).
