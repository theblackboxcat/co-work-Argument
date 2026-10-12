/* 位置信号（非线性写作）的验收。跑法：node tests/browser/run.js attention-position

   这一条是 2026-09-19 那个「伴写只在文末才可能出现」的正身：

   attentionSignals() 原来把
        atParagraphEnd = /\n\s*$/.test(before) || after.trim() === ''
   里那一项 `after.trim() === ''`（＝**光标后面一个字符都没有**，也就是在编辑区末尾）
   和"她刚写完一段"**并成了同一件事**。后果不是风格问题，是判据塌了：
       文末 → 段末恒真 → 后端 at_end 恒真 → 跳过"句中停顿"那一档 → 任何停顿都出声；
       中间 → 只剩"光标前一个字符是不是标点"在起作用 → 停在句中就沉默。
   她"很可能先写结尾再写中间"，而伴写只认文末——**默认了线性写作**。

   这里只测**前端采集**：四种位置必须分得开，而且"文末停在句中"不许再被判成段末。
   分档之后的判断在服务端，由 v3/attention.py 的自测与 v3/smoke_position.py 覆盖。
*/
try {
  var R = [];
  function t(n, f) {
    try {
      var v = f();
      R.push((v === true ? 'PASS' : (v === false ? 'FAIL' : 'INFO')) + ' | ' + n +
             (v === true || v === false ? '' : ' :: ' + v));
    } catch (e) { R.push('ERR  | ' + n + ' :: ' + (e && e.message)); }
  }
  var o = document.createElement('pre'); o.id = 'VR'; o.textContent = 'pending';
  document.body.appendChild(o);
  function dump() { o.textContent = '\n===VR-START===\n' + R.join('\n') + '\n===VR-END===\n'; }

  var P1 = '第一段的话。', P2 = '第二段的话。', P3 = '第三段的话。';
  var TEXT = P1 + '\n\n' + P2 + '\n\n' + P3;
  var P2_AT = P1.length + 2;                 // 第二段起点
  var P3_AT = P2_AT + P2.length + 2;         // 第三段起点
  var END = TEXT.length;

  /* ⚠️ 断言必须返回**严格 true/false**。
     runner 是按前缀分类的：`true`→PASS、`false`→FAIL、**其余一律 INFO**，
     而 INFO 不计入失败。所以写成 `return cond ? true : '实际是 ' + v` 的断言
     **永远不会红**——看着像在测，其实只在打印。诊断信息单独推一行 INFO。 */
  function eq(name, got, want) {
    var ok = (got === want);
    t(name, function () { return ok; });
    if (!ok) R.push('INFO |   ↑ 实际 ' + JSON.stringify(got) + '，要的是 ' + JSON.stringify(want));
  }

  // 把光标放到某个位置，再取一次信号。setSelection 是 toc-export.probe 用过的老办法。
  function sigAt(pos) {
    TRACK.events = [];
    ta.quill.setSelection(pos, 0);
    return attentionSignals();
  }

  (function () {
    document.querySelector('#viewsw .vs[data-view="write"]').click();
    ta.value = TEXT;

    eq('前置：纯文本按空行切成了三段', ta.value, TEXT);

    /* ── 1. 文末 ───────────────────────────────────────────── */
    var e = sigAt(END);
    eq('文末：after_chars = 0（后面没有字）', e.after_chars, 0);
    t('文末·停在句末：sentence_end 真、mid 假', function () {
      return e.at_sentence_end === true && e.mid_sentence === false;
    });
    // ★ 这一条是本次修复的正身。旧代码在文末把段末判成**恒真**。
    eq('★ 回归：文末·停在句末时，段末不许因为"后面没字"而变成真',
       e.at_paragraph_end, false);

    /* ── 2. 中间（段内，光标后面还有本段的字）────────────────── */
    var w = sigAt(P2_AT + 2);                 // 第二段，句中
    t('中间·段内：after_chars > 0', function () { return w.after_chars > 0; });
    eq('中间·段内：after_in_para 真（后面还有**本段**的字）', w.after_in_para, true);
    t('中间·段内停在句中：mid 真、段末假', function () {
      return w.mid_sentence === true && w.at_paragraph_end === false;
    });

    /* ── 3. 中间，落在段落边界上（后面跟的是**别的段**）───────── */
    //   after_in_para 说的是"光标之后到下一个空行之间还有没有字"，
    //   **不是**"光标前面有没有字"。所以第三段的**开头**属于"有"
    //   （整段都在她后面），真正的"两段之间"是**第二段末尾**——
    //   段落分隔符紧贴在光标后面。
    var b = sigAt(P3_AT);
    eq('第三段开头：after_in_para 真（后面整段都是已有的字）', b.after_in_para, true);

    var m = sigAt(P3_AT - 2);                 // 第二段末尾（句号之后，紧接空行）
    t('第二段末尾：句末真、段末假、after_in_para 假（这才是"站在两段之间"）',
       function () {
         return m.at_sentence_end === true && m.at_paragraph_end === false
           && m.after_in_para === false;
       });

    // 光标停在空行上（敲了回车、还没写）：before 以 \n 结尾 → 段末真。
    // 这是"她正要起一段"，**必须**能出声——不然新起一段的人反而得不到伴写。
    var onBlank = sigAt(P3_AT - 1);
    eq('停在空行上：段末真（正要起一段，得能出声）', onBlank.at_paragraph_end, true);
    eq('第三段开头（还没写字，光标前面是空行）：段末也真', sigAt(P3_AT).at_paragraph_end,
       true);

    /* ── 4. 文末与中间在"停顿落在哪儿"上对称 ──────────────────── */
    //   同一只手、同样的停顿，只换位置：文末与中间的 at_sentence_end / mid_sentence
    //   必须一致。**说不说**由后端判，前端这一层不许再偷偷偏向文末。
    var eSent = sigAt(END);                   // 文末（最后一段的句末）
    var wSent = sigAt(P2_AT + P2.length);     // 第二段句末（后面还有第三段）
    eq('对称：两处都停在句末 → sentence_end 都为真',
       eSent.at_sentence_end === true && wSent.at_sentence_end === true, true);
    eq('★ 对称：文末停在句末时段末是假（旧代码两边不对称）',
       eSent.at_paragraph_end, false);

    var wPartial = sigAt(P2_AT + 2);          // 中间写半句
    ta.value = TEXT + '她想';                 // 文末再写半句（放最后，别污染上面的断言）
    var ePartial = sigAt(ta.value.length);
    eq('★ 对称：两处都停在句中 → mid 都为真，且都不算段末',
       ePartial.mid_sentence === true && ePartial.at_paragraph_end === false
       && wPartial.mid_sentence === true && wPartial.at_paragraph_end === false, true);

    /* ── 5. 老路不受影响（默认就是老路：非窗口化）────────────── */
    var nowDoc = ta.value;
    eq('非窗口化：doc_chars 就是编辑区长度',
       attentionSignals().doc_chars, nowDoc.length);
    sigAt(nowDoc.length);
    eq('非窗口化：cursor_offset 就是光标位置',
       attentionSignals().cursor_offset, nowDoc.length);
    eq('非窗口化：文末 after_chars 为 0', attentionSignals().after_chars, 0);
  })();

  dump();
} catch (e) {
  var o2 = document.getElementById('VR');
  if (o2) o2.textContent = '\n===VR-START===\nERR | 探针最外层 :: ' + (e && e.message) +
    '\n===VR-END===\n';
}
