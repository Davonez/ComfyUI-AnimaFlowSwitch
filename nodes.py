"""Anima 流程总开关 + 控制网开关 —— 两个「整条支路要不要跑」的懒执行开关。

* AnimaFlowSwitch  一个下拉切 model / positive / negative，跳过时 Anima 支路完全不执行
* ControlNetSwitch 一个下拉决定模型要不要过控制网，跳过时控制网支路完全不执行

数据只做引用转交：不复制、不转换、不 detach、不搬设备。
仅用标准库，不 import comfy / torch，离线也能单测。
"""

from __future__ import annotations

import logging

__all__ = [
    "ANIMA_MODE_MIX",
    "ANIMA_MODE_SKIP",
    "ANIMA_MODES",
    "CN_SWITCH_USE",
    "CN_SWITCH_SKIP",
    "CN_SWITCH_MODES",
    "AnimaFlowSwitch",
    "ControlNetSwitch",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]

LOGGER = logging.getLogger("comfyui.animaflowswitch")
LOGGER.setLevel(logging.INFO)


# ---------------------------------------------------------------- Anima 流程总开关
# 一条下拉同时切 model / 正向 / 负向三条线，给「Anima 画师混合要不要走」这种
# "整条支路要么全用、要么全不用" 的场景用。
#
# 关键做法：Anima 那三个输入带 {"lazy": True}，再配 check_lazy_status：
#   * 跳过 -> check_lazy_status 返回空，Anima 那条支路（65 号节点那条）根本不会被
#     排进执行图。所以那条线上就算有节点被静音、甚至交空，也完全不影响出图；
#   * 不跳过 -> 才去要那三路的值；真拿到空值就自动回退到原始模型/原始条件，
#     绝不把 None 交给下游（65 就是被 None 坑死的）。
ANIMA_MODE_MIX = "不跳过（用 Anima 混合）"
ANIMA_MODE_SKIP = "跳过（用原始模型）"
ANIMA_MODES = [ANIMA_MODE_MIX, ANIMA_MODE_SKIP]


def _anima_mode_wants_mix(mode) -> bool:
    """「跳过…」开头的算跳过，其余（含空值、老文案）一律按不跳过处理。"""
    return not str(mode or "").strip().startswith("跳过")


class AnimaFlowSwitch:
    """Anima 流程总开关：一个下拉决定走不走 Anima 混合，模型和正负条件一起切。"""

    DESCRIPTION = (
        "一个下拉当总开关，同时切「model / 正向 / 负向」三条线：\n"
        "不跳过 = 用 Anima 混合后的模型和它的正向条件；\n"
        "跳过 = 用原始模型 + 普通 CLIPTextEncode 的条件，并且 Anima 那条支路完全不执行。\n"
        "不跳过时如果 Anima 模型是空的，会自动回退到原始模型并在控制台说明，不会把空值交给下游。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "模式": (
                    ANIMA_MODES,
                    {
                        "default": ANIMA_MODE_MIX,
                        "tooltip": (
                            "不跳过=用 Anima 那条支路的模型和条件；"
                            "跳过=用原始模型，Anima 支路连执行都不会执行。"
                        ),
                    },
                ),
            },
            "optional": {
                "model": (
                    "MODEL",
                    {"tooltip": "原始模型：不经过 Anima 混合，跳过时用它。"},
                ),
                "positive": (
                    "CONDITIONING",
                    {"tooltip": "原始正向条件：跳过时用它；不跳过时当 Anima 正向没接的兜底。"},
                ),
                "negative": (
                    "CONDITIONING",
                    {"tooltip": "负向条件，两条路共用（没接 Anima 负向时也用它）。"},
                ),
                "anima_model": (
                    "MODEL",
                    {
                        "lazy": True,
                        "tooltip": "Anima 混合后的模型（接 65 号节点的 model 输出）。",
                    },
                ),
                "anima_positive": (
                    "CONDITIONING",
                    {
                        "lazy": True,
                        "tooltip": "Anima 那条的正向条件（接 65 号节点的 base_prompt 输出）。",
                    },
                ),
                "anima_negative": (
                    "CONDITIONING",
                    {
                        "lazy": True,
                        "tooltip": "可选：Anima 那条单独的负向条件；不接就沿用 negative。",
                    },
                ),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("model", "positive", "negative")
    OUTPUT_TOOLTIPS = (
        "交给采样器的模型：不跳过=Anima 混合后的，跳过=原始模型。",
        "正向条件：不跳过=Anima 那条，跳过=原始的。",
        "负向条件：两条路共用。",
    )
    FUNCTION = "apply"
    CATEGORY = "Switch"
    OUTPUT_NODE = False

    # 这三个是懒输入：跳过模式下不去要它们的值，上游那一整条支路就不执行。
    ANIMA_INPUTS = ("anima_model", "anima_positive", "anima_negative")

    def check_lazy_status(self, 模式=ANIMA_MODE_MIX, **kwargs):
        """跳过模式 -> 返回空：Anima 支路一个节点都不会跑。"""
        if not _anima_mode_wants_mix(模式):
            return []
        # 连上了但还没算出来的（值为 None）才去要；压根没接的不提，免得无谓报错。
        return [
            name
            for name in self.ANIMA_INPUTS
            if name in kwargs and kwargs[name] is None
        ]

    def apply(
        self,
        模式=ANIMA_MODE_MIX,
        model=None,
        positive=None,
        negative=None,
        anima_model=None,
        anima_positive=None,
        anima_negative=None,
        unique_id=None,
    ):
        wants_mix = _anima_mode_wants_mix(模式)
        tag = f"[Anima开关#{unique_id}]" if unique_id is not None else "[Anima开关]"

        if wants_mix:
            if anima_model is None:
                LOGGER.warning(
                    "%s 不跳过，但 Anima 模型那条线是空的（65 被静音了？上游开关交空了？），"
                    "已回退到原始模型。",
                    tag,
                )
            use_model = anima_model if anima_model is not None else model
            use_positive = anima_positive if anima_positive is not None else positive
            use_negative = anima_negative if anima_negative is not None else negative
        else:
            use_model, use_positive, use_negative = model, positive, negative

        if use_model is None:
            raise ValueError(
                f"{tag} 没有模型可用：model 和 anima_model 都是空的。"
                "先看模型那条线上有没有节点被静音。"
            )
        if use_positive is None:
            raise ValueError(
                f"{tag} 正向条件没接："
                + (
                    "跳过模式必须接 positive。"
                    if not wants_mix
                    else "请接 positive 或 anima_positive。"
                )
            )
        if use_negative is None:
            raise ValueError(f"{tag} 负向条件没接：采样器要 negative。")

        LOGGER.info(
            "%s 本次：%s",
            tag,
            "不跳过（用 Anima 混合）" if wants_mix else "跳过（用原始模型）",
        )
        return (use_model, use_positive, use_negative)


# ---------------------------------------------------------------- 控制网开关
# 「控制网」这种"给模型打一层补丁"的阶段，一个下拉决定走不走它。
# 和 Anima 流程总开关一样：cn_model 是懒输入，跳过时不光不用它的值，上游整条控制网
# 支路（Canny / 取图 / LLLite）都不会被排进执行图 —— 关闭时是真的不花时间。
CN_SWITCH_USE = "不跳过（用控制网）"
CN_SWITCH_SKIP = "跳过（不用控制网）"
CN_SWITCH_MODES = [CN_SWITCH_USE, CN_SWITCH_SKIP]


def _cn_switch_wants_use(mode) -> bool:
    """「跳过…」开头的算跳过，其余（含空值、老文案）一律按不跳过处理。"""
    return not str(mode or "").strip().startswith("跳过")


class ControlNetSwitch:
    """控制网开关：一个下拉决定模型要不要先过控制网。"""

    DESCRIPTION = (
        "一个下拉决定要不要走控制网：\n"
        "不跳过 = 用控制网处理后的模型（cn_model），再接后面的 Anima / 采样；\n"
        "跳过 = 直接用原始模型，控制网那一整条支路完全不执行（懒执行）。\n"
        "不跳过但控制网模型是空的（控制网节点被静音了？）会自动回退到原始模型并在控制台提示。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "模式": (
                    CN_SWITCH_MODES,
                    {
                        "default": CN_SWITCH_SKIP,
                        "tooltip": (
                            "不跳过=模型先过控制网（吃 cn_model）；"
                            "跳过=直接用原始模型，控制网那条支路连执行都不执行。"
                        ),
                    },
                ),
            },
            "optional": {
                "model": (
                    "MODEL",
                    {"tooltip": "原始模型：不经过控制网，跳过时用它。"},
                ),
                "cn_model": (
                    "MODEL",
                    {
                        "lazy": True,
                        "tooltip": "控制网处理后的模型（接 LLLite / 控制网应用节点的 MODEL 输出）。",
                    },
                ),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    OUTPUT_TOOLTIPS = ("交给下一段的模型：不跳过=控制网处理后的，跳过=原始模型。",)
    FUNCTION = "apply"
    CATEGORY = "Switch"
    OUTPUT_NODE = False

    def check_lazy_status(self, 模式=CN_SWITCH_SKIP, **kwargs):
        """跳过模式 -> 返回空：控制网支路一个节点都不会跑。"""
        if not _cn_switch_wants_use(模式):
            return []
        return ["cn_model"] if "cn_model" in kwargs and kwargs["cn_model"] is None else []

    def apply(self, 模式=CN_SWITCH_SKIP, model=None, cn_model=None, unique_id=None):
        wants_cn = _cn_switch_wants_use(模式)
        tag = f"[控制网开关#{unique_id}]" if unique_id is not None else "[控制网开关]"

        if wants_cn and cn_model is None:
            LOGGER.warning(
                "%s 不跳过，但控制网模型那条线是空的（控制网节点被静音了？），"
                "已回退到原始模型。",
                tag,
            )

        use_cn = wants_cn and cn_model is not None
        use_model = cn_model if use_cn else model
        if use_model is None:
            raise ValueError(
                f"{tag} 没有模型可用：model 和 cn_model 都是空的。"
                "先看模型那条线上有没有节点被静音。"
            )

        LOGGER.info("%s 本次：%s", tag, "用控制网" if use_cn else "不用控制网")
        return (use_model,)

NODE_CLASS_MAPPINGS = {
    "AnimaFlowSwitch": AnimaFlowSwitch,
    "ControlNetSwitch": ControlNetSwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaFlowSwitch": "Anima 流程总开关 (Anima Flow Switch)",
    "ControlNetSwitch": "控制网开关 (ControlNet Switch)",
}
