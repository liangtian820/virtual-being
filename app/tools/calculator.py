"""计算工具：四则运算 + 百分比，安全解析（AST 白名单，不裸执行 eval）。

设计要点：
- 用 ast.parse 解析后按白名单递归求值，只允许数字常量、四则 BinOp、一元正负号；
  任何 Name / Call / Attribute / 其它运算符一律拒绝，防止注入。
- 支持中文输入归一化：中文运算符（加/减/乘/除）、"X 的 Y%"（如 "300 的 20%"）、
  "百分之 Y"、以及算式前后的意图词/语气词清洗。
- 任何错误输入返回明确错误信息（error 字段），绝不抛异常崩溃。
"""
import ast
import operator
import re
from typing import Dict, Optional, Union

Number = Union[int, float]


class CalculatorError(Exception):
    """计算过程中的业务错误（输入无法解析、非法运算符、除零等）。"""


# 允许的 BinOp 运算符白名单（仅四则）
_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

# 中文运算符 → 符号（长词在前，避免 "除以" 被 "除" 提前替换）
_CHINESE_OPS = (
    ("乘以", "*"),
    ("除以", "/"),
    ("加", "+"),
    ("减", "-"),
    ("乘", "*"),
    ("除", "/"),
)

# 开头意图词（算一下 / 帮我算 …）
_LEADING_PATTERN = re.compile(
    r"^(算一下|帮我算一下|帮我算|帮我计算|算一算|算算|帮我算算|计算|算个|算)+"
)
# 结尾语气词 / 疑问词
_TRAILING_PATTERN = re.compile(
    r"(等于多少|是多少|等于|多少|吧|呗|呀|呢|啊|哦|啦|？|\?|。|！|!|，|,|、|\s)+$"
)
# 百分比归一化（顺序敏感：含 "的" 的组合优先，再 "百分之"，最后单独 %）
_PCT_OF_CN = re.compile(r"(\d+(?:\.\d+)?)\s*的\s*百分之\s*(\d+(?:\.\d+)?)")
_PCT_OF = re.compile(r"(\d+(?:\.\d+)?)\s*的\s*(\d+(?:\.\d+)?)\s*%")
_PCT_CN = re.compile(r"百分之\s*(\d+(?:\.\d+)?)")
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _normalize(raw: str) -> str:
    """把中文算式归一化为可被 AST 解析的 ASCII 算式。"""
    expr = raw.strip()
    expr = _LEADING_PATTERN.sub("", expr).strip()
    expr = _TRAILING_PATTERN.sub("", expr).strip()
    for cn, sym in _CHINESE_OPS:
        expr = expr.replace(cn, sym)
    expr = expr.replace("（", "(").replace("）", ")")
    expr = _PCT_OF_CN.sub(r"\1 * \2 / 100", expr)
    expr = _PCT_OF.sub(r"\1 * \2 / 100", expr)
    expr = _PCT_CN.sub(r"\1 / 100", expr)
    expr = _PCT.sub(r"\1 / 100", expr)
    # 去掉残留空白（含中文全角空格）
    expr = re.sub(r"\s+", "", expr)
    return expr


def _eval_node(node: ast.AST) -> Number:
    """递归求值 AST 节点，仅放行白名单内的节点类型。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_BINOPS:
            raise CalculatorError(f"不支持的运算符：{type(node.op).__name__}（目前仅支持 + - * / 与百分比）")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        try:
            return _ALLOWED_BINOPS[op_type](left, right)
        except ZeroDivisionError as exc:
            raise CalculatorError("除数不能为 0 哦") from exc
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    raise CalculatorError(f"算式包含不支持的写法：{ast.dump(node)}（仅支持数字与 + - * /）")


def _safe_eval(expr: str) -> Number:
    """AST 白名单求值；解析失败/非法节点统一转 CalculatorError。"""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"算式格式无法解析：{expr!r}（{exc.msg}）") from exc
    value = _eval_node(tree.body)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return int(value)
        return round(value, 10)  # 消除 0.1+0.2 类浮点噪声
    return value


def calculate(expr: str) -> Dict[str, Optional[Union[Number, str]]]:
    """主入口：计算表达式，返回 {result, expression, error}。

    - result: 计算结果（整数返回 int，否则返回 float；失败为 None）
    - expression: 原始输入（原样保留，便于溯源）
    - error: 成功为 None，失败为明确的中文错误信息（绝不抛异常）
    """
    original = expr.strip()
    try:
        normalized = _normalize(original)
        if not normalized:
            raise CalculatorError("没有识别到算式，请提供类似 “3+5” 或 “300 的 20%” 的输入")
        value = _safe_eval(normalized)
        return {"result": value, "expression": original, "error": None}
    except CalculatorError as exc:
        return {"result": None, "expression": original, "error": str(exc)}
    except Exception as exc:  # 兜底：任何意外异常都转为明确错误，不崩溃
        return {"result": None, "expression": original, "error": f"计算失败：{exc}"}
