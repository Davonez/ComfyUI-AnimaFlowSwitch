**English** ｜ [中文](README.md)

# Anima Flow Switch + ControlNet Switch

Two lazy-evaluation switches for ComfyUI that decide whether a whole branch runs at all. All they do is a
reference hand-off: nothing is copied, converted, detached, or moved to another device — the object you pass
in is the exact same object that comes out.

| Node | One-liner |
|---|---|
| **Anima Flow Switch** (Anima 流程总开关, AnimaFlowSwitch) | One dropdown switches `model` / `positive` / `negative` together; when skipped, the Anima branch **does not run at all** |
| **ControlNet Switch** (控制网开关, ControlNetSwitch) | One dropdown decides whether the model goes through ControlNet first; when skipped, the ControlNet branch **does not run at all** |

> Version 1.0.0 ｜ standard library only ｜ no `comfy` / `torch` dependency, so the unit tests run offline ｜ MIT

---

## 1. Installation

```
ComfyUI/
└─ custom_nodes/
   └─ ComfyUI-AnimaFlowSwitch/     ← drop the whole folder in here (or git clone into custom_nodes)
      ├─ __init__.py
      ├─ nodes.py
      ├─ README.md
      ├─ README.en.md
      ├─ LICENSE
      ├─ pyproject.toml
      └─ tests/
```

1. Put the folder above into `custom_nodes` (or `git clone https://github.com/Davonez/ComfyUI-AnimaFlowSwitch.git` inside it);
2. Restart ComfyUI;
3. Hit `F5` in the browser once (the node list is fetched when the page loads);
4. Right-click → Add Node → `Switch`, or double-click the canvas and search for `anima` / `控制网`.

---

## 2. Anima Flow Switch (Anima 流程总开关)

```
Original model ────────────► model           ┌─► model
Original positive ─────────► positive        ├─► positive   ──► sampler
Shared negative ───────────► negative        └─► negative
Anima model (65) ──────────► anima_model
Anima positive (65) ───────► anima_positive
Anima negative (optional) ─► anima_negative
                             [Anima Flow Switch]
```

| Mode (`模式`) | Model | Positive | Negative | Anima branch |
|---|---|---|---|---|
| `不跳过（用 Anima 混合）` ("don't skip — use the Anima mix"), default | `anima_model`, falls back to `model` if empty | `anima_positive`, falls back to `positive` if empty | `anima_negative`, falls back to `negative` if empty | Runs |
| `跳过（用原始模型）` ("skip — use the original model") | `model` | `positive` | `negative` | **Never runs** |

* `anima_*` are **lazy inputs** (`lazy` + `check_lazy_status`): in skip mode the engine never even schedules
  that branch — it's not just that the values go unused, the branch is never computed. So with node 65 muted
  and the upstream switch handing over nothing, skipping still renders.
* Not skipping, but the Anima model input is empty → it automatically falls back to the original model and
  prints one line to the console:
  `[Anima开关#110] 不跳过，但 Anima 模型那条线是空的（65 被静音了？上游开关交空了？），已回退到原始模型。`
* Both models empty, or positive/negative not connected at all → it raises a Chinese `ValueError` that spells
  out which one is missing, instead of letting something downstream blow up on
  `'NoneType' object has no attribute ...`.

---

## 3. ControlNet Switch (控制网开关)

```
Original model (from LoRA) ───────► model     ┌─► model ──► downstream Anima / sampler
ControlNet model (LLLite, etc.) ──► cn_model  ┘
                                    [ControlNet Switch]
```

| Mode (`模式`) | Output | ControlNet branch |
|---|---|---|
| `不跳过（用控制网）` ("don't skip — use ControlNet") | `cn_model`, falls back to `model` if empty | Runs |
| `跳过（不用控制网）` ("skip — don't use ControlNet"), default | `model` | **Never runs** |

Same mechanism as the Anima switch: `cn_model` is a lazy input, so when skipping, not a single Canny /
image-loading / LLLite node runs; if you don't skip but the ControlNet side is empty (the ControlNet node is
muted, or the chain is broken), it falls back to the original model and logs a warning.

---

## 4. Using both together: four "cases"

```
LoRA model ──┬─► [ControlNet Switch].model ───┐
             └─► [ControlNet Switch].cn_model ┴─► model ──► 65.AnimaArtistCrossAttn ──┐
                                       │                                              ├─► [Anima Flow Switch] ─► sampler
                Regular positive ──────┼─► positive                                   │
                        Negative ──────┼─► negative                                   │
                  65.base_prompt ──────┴─► anima_positive ────────────────────────────┘
```

| ControlNet Switch | Anima Switch | Result |
|---|---|---|
| `跳过（不用控制网）` | `跳过（用原始模型）` | The LoRA model goes straight into sampling (neither ControlNet nor Anima runs) |
| `跳过（不用控制网）` | `不跳过（用 Anima 混合）` | ControlNet is skipped, but the Anima mix still happens |
| `不跳过（用控制网）` | `跳过（用原始模型）` | ControlNet takes effect, but there's no Anima mix |
| `不跳过（用控制网）` | `不跳过（用 Anima 混合）` | Everything on |

The two switches are independent, and no combination ever hands `None` downstream.

---

## 5. FAQ

**Q: Installed it, but it's not in the menu?**
Check the console for `IMPORT FAILED` first, then hit `F5` to refresh the browser. Searching `anima` / `控制网` should bring it up either way.

**Q: When skipping, do those upstream nodes really not run?**
They really don't. Lazy inputs never enter the execution graph, so skip mode doesn't pull dependencies for
them. You can see it in the log, too: when skipping, that branch's own log lines never show up (e.g. Anima's
`[AnimaCrossAttn] ...`, or the ControlNet preview).

**Q: I'm not skipping, but the upstream is muted/broken. What happens?**
It falls back to the original model/positive and logs a warning — no error, nothing empty handed on, and the
render keeps going. Only when there's nothing left to fall back to (both the original model and the
Anima/ControlNet model are empty) does it raise the Chinese error.

**Q: Can I install it alongside the `ComfyUI-MuteBypassSwitch` pack?**
You can, but **don't install both at once**: that pack also ships `AnimaFlowSwitch` / `ControlNetSwitch` under
the same names, so the node types get registered twice. Keep only one — the node type names in workflows are
identical, so they're interchangeable.

**Q: Does it affect image quality, or make things slower?**
It doesn't. The switch itself only does one reference hand-off of the model/conditioning — no tensor math;
when skipping you actually save the whole branch's compute.

---

## 6. Tests

The offline unit tests don't need ComfyUI running (any Python 3.10+):

```powershell
python tests\test_anima_flow_switch.py     # 56 tests
python tests\test_controlnet_switch.py     # 37 tests
```

Coverage: node definition/registration, mode-label compatibility, which inputs lazy evaluation actually
requests, a two-round executor simulation (no duplicate requests, no infinite loops), how the three lines
switch, empty-value fallback + warning, the Chinese error on missing inputs, and object identity staying
unchanged.

Real-machine check (local ComfyUI on 8188, 2026-10-21): wired into an Anima workflow, "skip" took 46.2s and
"don't skip" 28.0s, both successful; the skip run's log contained no `[AnimaAdapterMixer]` / `[AnimaCrossAttn]`,
which shows node 65 really didn't execute.

---

## 7. License

MIT. See [LICENSE](LICENSE).
