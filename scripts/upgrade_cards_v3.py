"""批量升级 40 目录岗位卡 v2 -> v3：插入固定规则块。

处理：01-高管层 ~ 06-支撑线 下的全部岗位卡。
插入内容：
  1. 工具白名单：联网检索规则
  2. 成功标准：主动筛查
  3. 协作接口前：生命周期节
  4. 链接规范前：交接责任
  5. 变更日志：v0.3.0 条目
  6. 版本号 v0.2.0 -> v0.3.0
"""
import os
import re

BASE = r"E:\knoliage\ai知识库\40 · Agent 与角色治理"

NET = "- **联网检索**：联网 = 读取工具（默认允许；命中高风险/敏感 → 授权）；禁止无来源结论"
SCREEN = "- **主动筛查**：交付前对照验收标准逐项自检；主动发现越权/风险/信息缺口并上报"
LIFECYCLE = """## 生命周期（权限与停用）
- **权限边界**：允许动作 + 操作范围；越界即上报，不自行扩权
- **阶段停用**：任务/阶段完成 → 角色停止，交付物归档
- **退役条件**（报总控/用户批准）：持续不合格 / 被其他角色取代 / 需求消失 / 权限冲突无法解决
- **退役动作**：停用角色 → 归档交付物与证据 → 变更日志登记

"""
HANDOFF = "- **交接责任**：移交方（交付物+证据完整、摘要交接、列明未完成项与风险）；接收方（核对验收、基于证据续接、缺失上报）"
CHANGELOG = "- 2026-08-16 `v0.3.0`：补协作契约（输入/交付/关系/交接）、联网检索、主动筛查、生命周期"


def upgrade_card(path: str) -> bool:
    """升级一张岗位卡，返回是否改动。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    original = text

    text = text.replace("version: 0.2.0", "version: 0.3.0")
    # 1. 联网检索：插到"- 白名单工具："前
    if re.search(r"(?m)^- 白名单工具：", text) and "联网检索" not in text:
        text = re.sub(r"(?m)^- 白名单工具：", NET + "\n- 白名单工具：", text, count=1)
    # 2. 主动筛查：插到"- 行动层："行后
    if "主动筛查" not in text:
        text = re.sub(r"(?m)^- 行动层：[^\n]*", lambda m: m.group(0) + "\n" + SCREEN, text, count=1)
    # 3. 生命周期节：插到"## 协作接口 Collaboration"前
    if "## 生命周期" not in text:
        text = text.replace("## 协作接口 Collaboration", LIFECYCLE + "## 协作接口 Collaboration", 1)
    # 4. 交接责任：插到"## 链接规范"前（协作接口节末尾）
    if "交接责任" not in text:
        text = text.replace("## 链接规范 Link Convention（强制）", HANDOFF + "\n\n## 链接规范 Link Convention（强制）", 1)
    # 5. 变更日志 v0.3.0
    if "v0.3.0" not in text:
        text = text.replace("- 2026-08-16 `v0.2.0`：重写为规则内联版", "- 2026-08-16 `v0.2.0`：重写为规则内联版\n" + CHANGELOG, 1)

    if text != original:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return True
    return False


def main() -> None:
    updated, skipped = 0, 0
    for root, _dirs, files in os.walk(BASE):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(root, fn)
            if not re.search(r"\\0[1-6]-", path):
                continue  # 只处理六线岗位卡
            if upgrade_card(path):
                updated += 1
            else:
                skipped += 1
    print(f"updated={updated} skipped={skipped}")


if __name__ == "__main__":
    main()
