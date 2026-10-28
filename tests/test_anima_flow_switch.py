"""Anima 流程总开关：离线单测（不用启动 ComfyUI）。

重点验三件事：
  1. 跳过模式下 check_lazy_status 返回空 —— 这就是"Anima 支路根本不会被排进执行图"的依据；
  2. 不跳过模式下才去要 Anima 那三路；真拿到空值就回退，绝不把 None 交给下游；
  3. 三条线（model / positive / negative）切得对不对、对象还是不是原来那个。
"""

from __future__ import annotations

import importlib.util
import logging
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
NODES_PY = HERE.parent / "nodes.py"

spec = importlib.util.spec_from_file_location("mbs_nodes_anima", NODES_PY)
mod = importlib.util.module_from_spec(spec)
sys.modules["mbs_nodes_anima"] = mod
spec.loader.exec_module(mod)

Node = mod.AnimaFlowSwitch
MIX = mod.ANIMA_MODE_MIX
SKIP = mod.ANIMA_MODE_SKIP

# 测试里别让日志往 stderr 跑（PowerShell 会把 stderr 当成执行失败），
# 下面 [4] 会自己挂一个 handler 来抓日志。
mod.LOGGER.propagate = False
mod.LOGGER.addHandler(logging.NullHandler())

ok = 0


def check(name, cond, extra=""):
    global ok
    if not cond:
        raise AssertionError(f"FAIL: {name} {extra}")
    ok += 1
    print(f"  [ok] {name}")


class Obj:
    """假装是 MODEL / CONDITIONING：只关心是不是同一个对象。"""

    def __init__(self, tag):
        self.tag = tag

    def __repr__(self):
        return f"<{self.tag}>"


# ---------------------------------------------------------------- 节点定义
print("[1] 节点定义 (INPUT_TYPES / 注册)")

it = Node.INPUT_TYPES()
required, optional = it["required"], it["optional"]
check("mode is required", "mode" in required)
check("mode has exactly two options", list(required["mode"][0]) == [MIX, SKIP])
check("mode defaults to mix", required["mode"][1]["default"] == MIX)
check("六个链路输入全都是可选", set(optional) == {
    "model", "positive", "negative", "anima_model", "anima_positive", "anima_negative",
})
check("model 是 MODEL", optional["model"][0] == "MODEL")
check("positive/negative 是 CONDITIONING",
      optional["positive"][0] == "CONDITIONING" and optional["negative"][0] == "CONDITIONING")
check("anima_* 声明了 lazy",
      all(optional[n][1].get("lazy") is True for n in Node.ANIMA_INPUTS))
check("非 Anima 的三路没有 lazy", all("lazy" not in optional[n][1] for n in ("model", "positive", "negative")))
check("三个输出", Node.RETURN_TYPES == ("MODEL", "CONDITIONING", "CONDITIONING"))
check("输出名对", Node.RETURN_NAMES == ("model", "positive", "negative"))
check("hidden unique_id", it["hidden"] == {"unique_id": "UNIQUE_ID"})
check("注册进 NODE_CLASS_MAPPINGS", mod.NODE_CLASS_MAPPINGS.get("AnimaFlowSwitch") is Node)
check("has an English display name", "Anima" in mod.NODE_DISPLAY_NAME_MAPPINGS["AnimaFlowSwitch"])

# 模式文案的兼容性：老工作流/写坏的字符串不能把「跳过」误判成「不跳过」
check("空模式按不跳过", mod._anima_mode_wants_mix("") is True)
check("None 模式按不跳过", mod._anima_mode_wants_mix(None) is True)
check("跳过 -> False", mod._anima_mode_wants_mix(SKIP) is False)
check("不跳过 -> True", mod._anima_mode_wants_mix(MIX) is True)
check("只写「跳过」也认", mod._anima_mode_wants_mix("跳过") is False)
check("「跳过（原始）」这种新文案也认", mod._anima_mode_wants_mix("跳过（原始）") is False)

# ---------------------------------------------------------------- 懒执行语义
print("[2] 懒执行：跳过时不去要 Anima 那三路")

n = Node()
raw_m, raw_p, raw_n = Obj("raw_model"), Obj("raw_pos"), Obj("raw_neg")
ani_m, ani_p, ani_n = Obj("ani_model"), Obj("ani_pos"), Obj("ani_neg")

check("跳过 + Anima 全接但都还没算 -> 一个都不要",
      n.check_lazy_status(mode=SKIP, model=raw_m, anima_model=None, anima_positive=None,
                          anima_negative=None) == [])
check("跳过 + 全空 -> 还是要空", n.check_lazy_status(mode=SKIP) == [])
check("不跳过 + 三路都还没算 -> 三个都要",
      n.check_lazy_status(mode=MIX, anima_model=None, anima_positive=None,
                          anima_negative=None) == list(Node.ANIMA_INPUTS))
check("不跳过 + 只接了 anima_model -> 只要它",
      n.check_lazy_status(mode=MIX, anima_model=None) == ["anima_model"])
check("不跳过 + 值都到齐了 -> 不要再要",
      n.check_lazy_status(mode=MIX, anima_model=ani_m, anima_positive=ani_p) == [])
check("不跳过 + 一路都没接 -> 不瞎要", n.check_lazy_status(mode=MIX) == [])

# ---------------------------------------------------------------- 三条线怎么切
print("[3] 切换：model / positive / negative 各自取哪一路")

got = n.apply(mode=MIX, model=raw_m, positive=raw_p, negative=raw_n,
              anima_model=ani_m, anima_positive=ani_p, unique_id=65)
check("不跳过：模型来自 Anima", got[0] is ani_m)
check("不跳过：正向来自 Anima", got[1] is ani_p)
check("不跳过：负向回落到共用负向", got[2] is raw_n)

got = n.apply(mode=MIX, model=raw_m, positive=raw_p, negative=raw_n,
              anima_model=ani_m, anima_positive=ani_p, anima_negative=ani_n)
check("不跳过：接了 Anima 负向就用它", got[2] is ani_n)

got = n.apply(mode=SKIP, model=raw_m, positive=raw_p, negative=raw_n,
              anima_model=ani_m, anima_positive=ani_p, anima_negative=ani_n)
check("跳过：模型回原始", got[0] is raw_m)
check("跳过：正向回原始", got[1] is raw_p)
check("跳过：负向回原始", got[2] is raw_n)

# 回调 / 直接调用不传模式时的默认行为
got = Node().apply(model=raw_m, positive=raw_p, negative=raw_n)
check("默认（不跳过）没 Anima 值 -> 回退原始", got == (raw_m, raw_p, raw_n))

# 不跳过但 Anima 只接了模型：正向、负向各自找兜底
got = n.apply(mode=MIX, model=raw_m, positive=raw_p, negative=raw_n, anima_model=ani_m)
check("Anima 只接模型：正向回原始", got[1] is raw_p)
check("Anima 只接模型：负向回原始", got[2] is raw_n)

# 假值不能被当成"没值"
zero_pos = Obj("empty_cond")
check("正向是 0/空 也不会被换成另一路",
      n.apply(mode=SKIP, model=raw_m, positive=zero_pos, negative=raw_n,
              anima_positive=ani_p)[1] is zero_pos)

# ---------------------------------------------------------------- 空值兜底（这次事故的根因）
print("[4] 空值兜底：绝不把 None 交给下游")

records = []


class Capture(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())


logger = mod.LOGGER
handler = Capture()
logger.addHandler(handler)
try:
    got = n.apply(mode=MIX, model=raw_m, positive=raw_p, negative=raw_n,
                  anima_model=None, anima_positive=ani_p, unique_id=65)
finally:
    logger.removeHandler(handler)
check("Anima 模型是空 -> 用原始模型", got[0] is raw_m)
check("logged a fallback warning", any("falling back to the original model" in r for r in records), records)
check("warning 里带节点号", any("#65" in r for r in records), records)

# ---------------------------------------------------------------- 明确报错
print("[5] 真没法救的时候，报明确的英文错误")


def expect_error(name, **kwargs):
    try:
        Node().apply(**kwargs)
    except ValueError as e:
        check(name, True)
        return str(e)
    raise AssertionError(f"FAIL: {name} 没有报错")


msg = expect_error("两个模型都空 -> 报错", mode=MIX, positive=raw_p, negative=raw_n)
check("报错说清是模型的问题", "no model available" in msg, msg)
msg = expect_error("跳过但没接正向 -> 报错", mode=SKIP, model=raw_m, negative=raw_n)
check("报错说清是正向的问题", "positive conditioning is not connected" in msg, msg)
msg = expect_error("没接负向 -> 报错", mode=SKIP, model=raw_m, positive=raw_p)
check("报错说清是负向的问题", "negative conditioning is not connected" in msg, msg)

# ---------------------------------------------------------------- 执行器流程模拟
print("[6] 按 execution.py 的顺序模拟一遍（懒输入两轮）")


def run_prompt(mode, connected, resolved):
    """尽量照着引擎的行为走：

    * 连上的懒输入先当 None 并记进 missing_keys；
    * check_lazy_status 返回的名字要满足 "不在 input_data_all 里 或 在 missing_keys 里"；
    * 取到值以后再看一次 check_lazy_status（应该不再要东西）。
    """
    input_data_all, missing = {}, set()
    for name, is_connected in connected.items():
        if not is_connected:
            continue
        input_data_all[name] = None if name in Node.ANIMA_INPUTS else resolved.get(name)
        if name in Node.ANIMA_INPUTS:
            missing.add(name)
    input_data_all["mode"] = mode

    wanted = n.check_lazy_status(**input_data_all)
    need = [x for x in wanted if x not in input_data_all or x in missing]
    for name in need:
        input_data_all[name] = resolved.get(name)
        missing.discard(name)
    again = n.check_lazy_status(**input_data_all)
    never_asked = [x for x in again if x not in input_data_all or x in missing]
    return need, never_asked, n.apply(**input_data_all)


connected_all = {
    "model": True, "positive": True, "negative": True,
    "anima_model": True, "anima_positive": True, "anima_negative": True,
}
values = {"model": raw_m, "positive": raw_p, "negative": raw_n,
          "anima_model": ani_m, "anima_positive": ani_p, "anima_negative": ani_n}

need, again, out = run_prompt(SKIP, connected_all, values)
check("跳过：一个懒输入都不去要", need == [], need)
check("跳过：不会再要第二轮", again == [], again)
check("跳过：走原始三条线", out == (raw_m, raw_p, raw_n))

need, again, out = run_prompt(MIX, connected_all, values)
check("不跳过：三路都要了一轮", sorted(need) == sorted(Node.ANIMA_INPUTS), need)
check("不跳过：第二轮不再要", again == [], again)
check("不跳过：走 Anima 三条线", (out[0] is ani_m and out[1] is ani_p and out[2] is ani_n))

# 不跳过 + Anima 上游算出来就是空（比如上游开关交空）：不能死循环，也不能交空
values_empty = dict(values, anima_model=None, anima_positive=None)
need, again, out = run_prompt(MIX, connected_all, values_empty)
check("不跳过但 Anima 是空：不回退成死循环", again == [], again)
check("不跳过但 Anima 是空：交原始模型", out[0] is raw_m)
check("不跳过但 Anima 是空：交原始正向", out[1] is raw_p)

# 跳过 + Anima 支路整个没接（等于那条线不存在）
connected_skip = {
    "model": True, "positive": True, "negative": True,
    "anima_model": False, "anima_positive": False, "anima_negative": False,
}
need, again, out = run_prompt(SKIP, connected_skip, values)
check("跳过 + Anima 没接：不去要", need == [] and again == [])
check("跳过 + Anima 没接：仍能出三条线", out == (raw_m, raw_p, raw_n))

print(f"\n全部通过：{ok} 项")
