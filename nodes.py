"""Anima flow switch + ControlNet switch - two lazy-execution branch switches.

* AnimaFlowSwitch   one dropdown switches model / positive / negative together; when the
                    switch is set to skip, the Anima branch is not placed on the execution
                    graph at all, so it genuinely does not run.
* ControlNetSwitch  one dropdown decides whether the model goes through ControlNet; when
                    skipped, the whole ControlNet branch is not executed either.

Data is passed by reference only: no copies, no conversion, no detach, no device moves.
Standard library only - comfy / torch are never imported, so the nodes can be unit-tested
offline.
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


# ---------------------------------------------------------------- Anima flow switch
# One dropdown switches model / positive / negative at once, for branches that must be
# either fully used or fully skipped ("should the Anima artist mix run?").
#
# The key trick: the three Anima inputs carry {"lazy": True} plus check_lazy_status:
#   * skip  -> check_lazy_status returns nothing, so the Anima branch (node 65 and
#              everything upstream of it) is never scheduled. A muted or empty node on
#              that branch therefore cannot break the render at all;
#   * mix   -> the three values are requested; if they really are empty, the node falls
#              back to the original model / conditioning instead of handing None
#              downstream (which is what used to break node 65).
ANIMA_MODE_MIX = "mix"
ANIMA_MODE_SKIP = "skip"
ANIMA_MODES = [ANIMA_MODE_MIX, ANIMA_MODE_SKIP]


def _anima_mode_wants_mix(mode) -> bool:
    """Return True unless the mode means skip (legacy Chinese values are accepted too)."""
    text = str(mode or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered.startswith("skip") or lowered in ("off", "false", "0"):
        return False
    if text.startswith("跳过"):
        return False
    return True


class AnimaFlowSwitch:
    """One dropdown decides whether the Anima mix runs; model and conditioning switch together."""

    DESCRIPTION = (
        "One dropdown acts as a master switch for three links at once - model / positive / "
        "negative.\n"
        "Mix = use the Anima-mixed model and its positive conditioning.\n"
        "Skip = use the original model plus a normal CLIPTextEncode conditioning, and the "
        "Anima branch is not executed at all.\n"
        "When mixing, an empty Anima model falls back to the original model with a console "
        "warning, so None is never passed downstream."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (
                    ANIMA_MODES,
                    {
                        "default": ANIMA_MODE_MIX,
                        "tooltip": (
                            "Mix = use the model and conditioning from the Anima branch; "
                            "Skip = use the original model and never execute the Anima branch."
                        ),
                    },
                ),
            },
            "optional": {
                "model": (
                    "MODEL",
                    {"tooltip": "Original model: not Anima-mixed. Used when skipping."},
                ),
                "positive": (
                    "CONDITIONING",
                    {
                        "tooltip": "Original positive conditioning: used when skipping, and as "
                        "the fallback when the Anima positive is not connected."
                    },
                ),
                "negative": (
                    "CONDITIONING",
                    {
                        "tooltip": "Negative conditioning, shared by both paths (also used when "
                        "the Anima negative is not connected)."
                    },
                ),
                "anima_model": (
                    "MODEL",
                    {
                        "lazy": True,
                        "tooltip": "Anima-mixed model (wire the model output of node 65).",
                    },
                ),
                "anima_positive": (
                    "CONDITIONING",
                    {
                        "lazy": True,
                        "tooltip": "Anima positive conditioning (wire the base_prompt output "
                        "of node 65).",
                    },
                ),
                "anima_negative": (
                    "CONDITIONING",
                    {
                        "lazy": True,
                        "tooltip": "Optional: the Anima branch's own negative conditioning; "
                        "falls back to negative when not connected.",
                    },
                ),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("model", "positive", "negative")
    OUTPUT_TOOLTIPS = (
        "Model handed to the sampler: Anima-mixed when mixing, original when skipping.",
        "Positive conditioning: from the Anima branch when mixing, original when skipping.",
        "Negative conditioning: shared by both paths.",
    )
    FUNCTION = "apply"
    CATEGORY = "Switch"
    OUTPUT_NODE = False

    # Lazy inputs: in skip mode their values are never requested, so the whole upstream
    # branch is not executed.
    ANIMA_INPUTS = ("anima_model", "anima_positive", "anima_negative")

    def check_lazy_status(self, mode=ANIMA_MODE_MIX, **kwargs):
        """Skip mode -> nothing requested, so no node in the Anima branch runs."""
        if not _anima_mode_wants_mix(mode):
            return []
        # Only ask for inputs that are wired but not computed yet (value is None).
        # Inputs that are simply not connected are left alone to avoid pointless errors.
        return [
            name
            for name in self.ANIMA_INPUTS
            if name in kwargs and kwargs[name] is None
        ]

    def apply(
        self,
        mode=ANIMA_MODE_MIX,
        model=None,
        positive=None,
        negative=None,
        anima_model=None,
        anima_positive=None,
        anima_negative=None,
        unique_id=None,
    ):
        wants_mix = _anima_mode_wants_mix(mode)
        tag = f"[AnimaSwitch#{unique_id}]" if unique_id is not None else "[AnimaSwitch]"

        if wants_mix:
            if anima_model is None:
                LOGGER.warning(
                    "%s: mixing, but the Anima model link is empty (node 65 muted? an "
                    "upstream switch output nothing?); falling back to the original model.",
                    tag,
                )
            use_model = anima_model if anima_model is not None else model
            use_positive = anima_positive if anima_positive is not None else positive
            use_negative = anima_negative if anima_negative is not None else negative
        else:
            use_model, use_positive, use_negative = model, positive, negative

        if use_model is None:
            raise ValueError(
                f"{tag}: no model available - both model and anima_model are empty. "
                "Check whether a node on the model link is muted."
            )
        if use_positive is None:
            raise ValueError(
                f"{tag}: positive conditioning is not connected - "
                + (
                    "skip mode requires positive."
                    if not wants_mix
                    else "connect positive or anima_positive."
                )
            )
        if use_negative is None:
            raise ValueError(
                f"{tag}: negative conditioning is not connected - the sampler needs negative."
            )

        LOGGER.info(
            "%s: %s",
            tag,
            "mix (Anima)" if wants_mix else "skip (original model)",
        )
        return (use_model, use_positive, use_negative)


# ---------------------------------------------------------------- ControlNet switch
# For stages that patch the model (ControlNet, LLLite, ...): one dropdown decides whether
# the model goes through that stage. As above, cn_model is lazy, so skipping does not just
# ignore its value - the whole upstream ControlNet branch is never scheduled.
CN_SWITCH_USE = "use"
CN_SWITCH_SKIP = "skip"
CN_SWITCH_MODES = [CN_SWITCH_USE, CN_SWITCH_SKIP]


def _cn_switch_wants_use(mode) -> bool:
    """Return False only when the mode means skip (legacy Chinese values are accepted too)."""
    text = str(mode or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered.startswith("skip") or lowered in ("off", "false", "0"):
        return False
    if text.startswith("跳过"):
        return False
    return True


class ControlNetSwitch:
    """One dropdown decides whether the model goes through ControlNet first."""

    DESCRIPTION = (
        "One dropdown decides whether the ControlNet stage runs:\n"
        "Use = take the ControlNet-processed model (cn_model) and feed it to the next stage.\n"
        "Skip = use the original model directly; the whole ControlNet branch is not executed "
        "(lazy evaluation).\n"
        "If Use is selected but the ControlNet model is empty (ControlNet node muted?), the "
        "node falls back to the original model and says so in the console."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (
                    CN_SWITCH_MODES,
                    {
                        "default": CN_SWITCH_SKIP,
                        "tooltip": (
                            "Use = the model goes through ControlNet first (cn_model); "
                            "Skip = use the original model and never execute the ControlNet branch."
                        ),
                    },
                ),
            },
            "optional": {
                "model": (
                    "MODEL",
                    {"tooltip": "Original model: not processed by ControlNet. Used when skipping."},
                ),
                "cn_model": (
                    "MODEL",
                    {
                        "lazy": True,
                        "tooltip": "ControlNet-processed model (wire the MODEL output of the "
                        "LLLite / ControlNet apply node).",
                    },
                ),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    OUTPUT_TOOLTIPS = (
        "Model handed to the next stage: ControlNet-processed when using, original when skipping.",
    )
    FUNCTION = "apply"
    CATEGORY = "Switch"
    OUTPUT_NODE = False

    def check_lazy_status(self, mode=CN_SWITCH_SKIP, **kwargs):
        """Skip mode -> nothing requested, so no node in the ControlNet branch runs."""
        if not _cn_switch_wants_use(mode):
            return []
        return ["cn_model"] if "cn_model" in kwargs and kwargs["cn_model"] is None else []

    def apply(self, mode=CN_SWITCH_SKIP, model=None, cn_model=None, unique_id=None):
        wants_cn = _cn_switch_wants_use(mode)
        tag = (
            f"[ControlNetSwitch#{unique_id}]"
            if unique_id is not None
            else "[ControlNetSwitch]"
        )

        if wants_cn and cn_model is None:
            LOGGER.warning(
                "%s: use mode, but the ControlNet model link is empty (ControlNet node "
                "muted?); falling back to the original model.",
                tag,
            )

        use_cn = wants_cn and cn_model is not None
        use_model = cn_model if use_cn else model
        if use_model is None:
            raise ValueError(
                f"{tag}: no model available - both model and cn_model are empty. "
                "Check whether a node on the model link is muted."
            )

        LOGGER.info("%s: %s", tag, "with ControlNet" if use_cn else "without ControlNet")
        return (use_model,)


NODE_CLASS_MAPPINGS = {
    "AnimaFlowSwitch": AnimaFlowSwitch,
    "ControlNetSwitch": ControlNetSwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaFlowSwitch": "Anima Flow Switch",
    "ControlNetSwitch": "ControlNet Switch",
}
