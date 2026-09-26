"""流式段落切分器：按 markdown 标题行把 LLM 输出切成具名段落，逐块标注 section（接口文档 1.4）。

分段链路的公共工具（JD 分析 / 陪练点评 / 模拟面试 / 面经复盘同用），与 `utils/sse.py` 同为协议层：
零业务依赖、可独立单测。

三条约定：

1. **标题行原样下发**（不吞）——「落库全文 == 所有 delta 拼接」成立，`section` 只是给前端的分段锚点与进度指示；
2. **仅行首判定**——块的第一个字符不是 `#` 就立即透传，不破坏打字机节奏；`#` 开头的行才缓冲到行尾判定
   （标题很短，这点等待可忽略）；
3. **识别不出标题就沿用当前 section**——LLM 未按约定格式输出时全文照发，等价于纯文本降级
   （SRS FR-006 异常场景），不会把内容错标进某一段。
"""

from collections.abc import Sequence


class SectionSplitter:
    """增量切分器：`feed()` 逐块吃 LLM 增量，`flush()` 收尾吐出残留。"""

    def __init__(self, rules: Sequence[tuple[Sequence[str], str]]) -> None:
        """`rules` 为（关键词组，section 标识）序列，任一关键词命中标题行即取该 section。"""
        self._rules = rules
        self._section: str | None = None
        self._buffer = ""
        self._at_line_start = True

    @property
    def section(self) -> str | None:
        """当前段落标识；首个标题出现前为 None（前端按未分段渲染）。"""
        return self._section

    def feed(self, chunk: str) -> list[tuple[str, str | None]]:
        """吃进一个增量块，返回 `[(文本, section), ...]` —— 一个块可能跨段落，故按段拆开返回。"""
        pieces: list[tuple[str, str | None]] = []
        pending = self._buffer + chunk
        self._buffer = ""
        while pending:
            if self._at_line_start and pending.startswith("#"):
                newline = pending.find("\n")
                if newline < 0:
                    # 行未结束，标题判定不了：留下等下一块（可能是被切开的标题行）
                    self._buffer = pending
                    return pieces
                line, pending = pending[: newline + 1], pending[newline + 1 :]
                self._section = self._match(line) or self._section
                pieces.append((line, self._section))
                continue
            self._at_line_start = False
            newline = pending.find("\n")
            if newline < 0:
                pieces.append((pending, self._section))
                break
            pieces.append((pending[: newline + 1], self._section))
            pending = pending[newline + 1 :]
            self._at_line_start = True
        return pieces

    def flush(self) -> list[tuple[str, str | None]]:
        """流结束收尾：吐出缓冲中的残留（无换行结尾的标题行按普通文本处理）。"""
        if not self._buffer:
            return []
        tail, self._buffer = self._buffer, ""
        self._at_line_start = False
        return [(tail, self._section)]

    def _match(self, line: str) -> str | None:
        """标题行 → section 标识（五段关键词互不重叠，命中任意一个即可）。"""
        text = line.lstrip("#").strip()
        for keywords, section in self._rules:
            if any(keyword in text for keyword in keywords):
                return section
        return None
