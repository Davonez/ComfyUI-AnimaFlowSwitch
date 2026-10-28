"""控制网开关：离线单测（不用启动 ComfyUI）。

重点：
  1. 跳过模式 check_lazy_status 返回空 -> 控制网那一整条支路根本不进执行图；
  2. 不跳过才去要 cn_model；
  3. 控制网是空的时候回退原始模型（打 warning），两个都空才报英文错。
"""

from __future__ import annotations

import importlib.util
import logging
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
NODES_PY = HERE.parent / "nodes.py"

spec = importlib.util.spec_from_file_location("mbs_nodes_cn", NODES_PY)
mod = importlib.util.module_from_spec(spec)
sys.modules["mbs_nodes_cn"] = mod
spec.loader.exec_module(mod)

Node = mod.ControlNetSwitch
USE = mod.CN_SWITCH_USE
SKIP = mod.CN_SWITCH_SKIP

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
    def __init__(self, tag):
        self.tag = tag

    def __repr__(self):
        return f"<{self.tag}>"


# ---------------------------------------------------------------- 节点定义
print("[1] 节点定义 / 注册")

it = Node.INPUT_TYPES()
check("「模式」必填", "mode" in it["required"])
check("两个选项", list(it["required"]["mode"][0]) == [USE, SKIP])
check("默认跳过控制网", it["required"]["mode"][1]["default"] == SKIP)
check("model / cn_model 可选", set(it["optional"]) == {"model", "cn_model"})
check("cn_model 是懒输入", it["optional"]["cn_model"][1].get("lazy") is True)
check("model 不是懒输入", "lazy" not in it["optional"]["model"][1])
check("只有一个 MODEL 输出", Node.RETURN_TYPES == ("MODEL",) and Node.RETURN_NAMES == ("model",))
check("hidden unique_id", it["hidden"] == {"unique_id": "UNIQUE_ID"})
check("已注册", mod.NODE_CLASS_MAPPINGS.get("ControlNetSwitch") is Node)
check("has an English display name", "ControlNet" in mod.NODE_DISPLAY_NAME_MAPPINGS["ControlNetSwitch"])

check("跳过 -> False", mod._cn_switch_wants_use(SKIP) is False)
check("只写「跳过」也认", mod._cn_switch_wants_use("跳过") is False)
check("不跳过 -> True", mod._cn_switch_wants_use(USE) is True)
check("空值按不跳过", mod._cn_switch_wants_use("") is True)
check("None 按不跳过", mod._cn_switch_wants_use(None) is True)

# ---------------------------------------------------------------- 懒执行
print("[2] 懒执行：跳过时不去要 cn_model")

n = Node()
raw, cn = Obj("raw"), Obj("cn")

check("跳过 + cn_model 没算 -> 不要", n.check_lazy_status(mode=SKIP, model=raw, cn_model=None) == [])
check("跳过 + 全空 -> 不要", n.check_lazy_status(mode=SKIP) == [])
check("不跳过 + cn_model 没算 -> 要它", n.check_lazy_status(mode=USE, cn_model=None) == ["cn_model"])
check("不跳过 + 值到了 -> 不要", n.check_lazy_status(mode=USE, cn_model=cn) == [])
check("不跳过 + 没接 -> 不瞎要", n.check_lazy_status(mode=USE) == [])

# ---------------------------------------------------------------- 切换
print("[3] 切换：输出原始模型还是控制网模型")

got, = n.apply(mode=SKIP, model=raw, cn_model=cn)
check("跳过：交原始模型（is 同一个对象）", got is raw)
got, = n.apply(mode=USE, model=raw, cn_model=cn)
check("不跳过：交控制网模型", got is cn)
got, = n.apply(mode=USE, model=raw)
check("不跳过但控制网空：回退原始模型", got is raw)
try:
    n.apply(mode=SKIP, model=None, cn_model=cn)
except ValueError as e:
    raise_ok = "no model available" in str(e)
else:
    raise_ok = False
check("跳过但原始模型空：报错（不能拿控制网的顶上）", raise_ok)

# ---------------------------------------------------------------- 空值兜底
print("[4] 空值兜底：回退时打 warning，绝不交空")

records = []


class Capture(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())


handler = Capture()
mod.LOGGER.addHandler(handler)
try:
    got, = n.apply(mode=USE, model=raw, cn_model=None, unique_id=111)
finally:
    mod.LOGGER.removeHandler(handler)
check("回退到原始模型", got is raw)
check("logged a fallback warning", any("falling back to the original model" in r for r in records), records)
check("warning 带节点号", any("#111" in r for r in records), records)

try:
    n.apply(mode=USE, unique_id=111)
except ValueError as e:
    check("两个都空 -> 英文报错", "no model available" in str(e), str(e))
else:
    raise AssertionError("FAIL: 两个都空没有报错")

# ---------------------------------------------------------------- 执行器模拟
print("[5] 按 execution.py 的顺序模拟（懒输入两轮）")


def run_prompt(mode, connected, resolved):
    input_data_all, missing = {}, set()
    for name, is_connected in connected.items():
        if not is_connected:
            continue
        input_data_all[name] = None if name == "cn_model" else resolved.get(name)
        if name == "cn_model":
            missing.add(name)
    input_data_all["mode"] = mode
    wanted = n.check_lazy_status(**input_data_all)
    need = [x for x in wanted if x not in input_data_all or x in missing]
    for name in need:
        input_data_all[name] = resolved.get(name)
        missing.discard(name)
    again = [x for x in n.check_lazy_status(**input_data_all) if x not in input_data_all or x in missing]
    return need, again, n.apply(**input_data_all)


conn = {"model": True, "cn_model": True}
vals = {"model": raw, "cn_model": cn}

need, again, out = run_prompt(SKIP, conn, vals)
check("跳过：一轮都不去要", need == [] and again == [], need)
check("跳过：交原始模型", out[0] is raw)

need, again, out = run_prompt(USE, conn, vals)
check("不跳过：要了一轮 cn_model", need == ["cn_model"], need)
check("不跳过：第二轮不再要", again == [], again)
check("不跳过：交控制网模型", out[0] is cn)

need, again, out = run_prompt(USE, {"model": True, "cn_model": True},
                              {"model": raw, "cn_model": None})
check("不跳过但控制网算出来是空：不死循环", again == [], again)
check("不跳过但控制网算出来是空：交原始模型", out[0] is raw)

need, again, out = run_prompt(SKIP, {"model": True, "cn_model": False}, vals)
check("跳过 + 控制网没接：不去要", need == [] and again == [])
check("跳过 + 控制网没接：仍能交模型", out[0] is raw)

print(f"\n全部通过：{ok} 项")
