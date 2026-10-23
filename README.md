[English](README.en.md) ｜ **中文**

# Anima 流程总开关 + 控制网开关

两个「整条支路要不要跑」的懒执行开关，给 ComfyUI 用。只做引用转交：不复制、不转换、
不 detach、不搬设备，传进去什么对象，吐出来就是同一个对象。

| 节点 | 一句话 |
|---|---|
| **Anima 流程总开关**（AnimaFlowSwitch） | 一个下拉同时切 `model` / `positive` / `negative`，跳过时 Anima 那条支路**完全不执行** |
| **控制网开关**（ControlNetSwitch） | 一个下拉决定模型要不要先过控制网，跳过时控制网那条支路**完全不执行** |

> 版本 1.0.0 ｜ 仅用标准库 ｜ 不依赖 `comfy` / `torch`，离线也能单测 ｜ MIT

---

## 1. 安装

```
ComfyUI/
└─ custom_nodes/
   └─ ComfyUI-AnimaFlowSwitch/     ← 把整个文件夹放进来（或者 git clone 到 custom_nodes）
      ├─ __init__.py
      ├─ nodes.py
      ├─ README.md
      ├─ README.en.md
      ├─ LICENSE
      ├─ pyproject.toml
      └─ tests/
```

1. 把上面的文件夹放进 `custom_nodes`（或者在里面 `git clone https://github.com/Davonez/ComfyUI-AnimaFlowSwitch.git`）；
2. 重启 ComfyUI；
3. 浏览器 `F5` 刷新一次（节点列表是页面加载时拉的）；
4. 右键 → Add Node → `Switch`，或者双击画布搜 `anima` / `控制网`。

---

## 2. Anima 流程总开关 (AnimaFlowSwitch)

```
原始模型 ──────────────► model            ┌─► model
原始正向 ──────────────► positive         ├─► positive   ──► 采样器
共用负向 ──────────────► negative         └─► negative
Anima 模型（65）───────► anima_model
Anima 正向（65）───────► anima_positive
（可选）Anima 负向 ────► anima_negative
                         [Anima 流程总开关]
```

| 模式 | 模型 | 正向 | 负向 | Anima 支路 |
|---|---|---|---|---|
| 不跳过（默认） | `anima_model`，空了回退 `model` | `anima_positive`，空了回退 `positive` | `anima_negative`，空了用 `negative` | 执行 |
| 跳过 | `model` | `positive` | `negative` | **完全不执行** |

* `anima_*` 是**懒输入**（`lazy` + `check_lazy_status`）：跳过模式下引擎根本不会去排那条支路，
  不光是不用它的值，是连算都不算。所以 65 号节点静音、上游开关交空，跳过依然能出图。
* 不跳过但 Anima 模型是空的 → 自动回退原始模型，并在控制台打一行
  `[Anima开关#110] 不跳过，但 Anima 模型那条线是空的（65 被静音了？上游开关交空了？），已回退到原始模型。`
* 两个模型都空、或正向/负向彻底没接 → 抛中文 `ValueError` 说清缺哪个，而不是让下游崩在
  `'NoneType' object has no attribute ...`。

---

## 3. 控制网开关 (ControlNetSwitch)

```
原始模型（LoRA 出来）────► model          ┌─► model ──► 后面的 Anima / 采样
控制网模型（LLLite 等）──► cn_model       ┘
                           [控制网开关]
```

| 模式 | 输出 | 控制网支路 |
|---|---|---|
| 不跳过（用控制网） | `cn_model`，空了回退 `model` | 执行 |
| 跳过（默认） | `model` | **完全不执行** |

和 Anima 开关同一套机制：`cn_model` 是懒输入，跳过时 Canny / 取图 / LLLite 一个节点都不会跑；
不跳过但控制网那路是空的（控制网节点被静音、或者链断了）会回退原始模型并打 warning。

---

## 4. 两个一起用：四种「情况」

```
LoRA 模型 ──┬─► [控制网开关].model ───┐
            └─► [控制网开关].cn_model ┴─► model ──► 65.AnimaArtistCrossAttn ────┐
                                                        │                       ├─► [Anima 流程总开关] ─► 采样器
                                     普通正向 ──────────┼─► positive            │
                                     负向 ──────────────┼─► negative            │
                                     65.base_prompt ────┴─► anima_positive ─────┘
```

| 控制网开关 | Anima 开关 | 结果 |
|---|---|---|
| 跳过 | 跳过 | LoRA 原始模型直接进采样（控制网、Anima 都不跑） |
| 跳过 | 不跳过 | 跳过控制网，但仍然做 Anima 混合 |
| 不跳过 | 跳过 | 控制网生效，但不做 Anima 混合 |
| 不跳过 | 不跳过 | 全开 |

两个开关互相独立，任何组合都不会把 `None` 交给下游。

---

## 5. 常见问题

**Q: 装完菜单里找不到？**
先看控制台有没有 `IMPORT FAILED`，再 `F5` 刷新浏览器。搜 `anima` / `控制网` 都能出来。

**Q: 跳过的时候，上游那些节点真的不跑吗？**
真的不跑。懒输入不进执行图，跳过模式不会为它拉依赖。日志里也能看出来：跳过时不会出现那条支路
自己的日志（比如 Anima 的 `[AnimaCrossAttn] ...`、控制网的预览）。

**Q: 不跳过，但上游是静的/断的，会怎样？**
回退到原始模型/原始正向，并打一行 warning，不报错、不交空，出图流程不中断。
只有「连回退都没有」（原始模型和 Anima/控制网模型都空）才报中文错。

**Q: 和 `ComfyUI-MuteBypassSwitch` 包能一起装吗？**
能装，但**别同时装**：那个包里也有同名的 `AnimaFlowSwitch` / `ControlNetSwitch`，节点类型会注册两遍。
只留一份即可，工作流里的节点类型名是一样的，互相通用。

**Q: 会不会影响出图质量 / 变慢？**
不会。开关本身只是把模型/条件引用转交一次，没有张量运算；跳过时反而省掉整条支路的计算。

---

## 6. 测试

离线单测不需要启动 ComfyUI（任意 Python 3.10+）：

```powershell
python tests\test_anima_flow_switch.py     # 56 项
python tests\test_controlnet_switch.py     # 37 项
```

覆盖：节点定义/注册、模式文案兼容、懒执行请求了哪些输入、执行器两轮模拟（不重复要、不死循环）、
三条线怎么切、空值回退 + warning、缺输入时的中文报错、对象引用不变。

真机验证（本机 ComfyUI 8188，2026-10-21）：接进 Anima 工作流后「跳过」46.2s / 「不跳过」28.0s
两次都成功；跳过那次日志里没有 `[AnimaAdapterMixer]` / `[AnimaCrossAttn]`，说明 65 号节点确实没执行。

---

## 7. 许可

MIT。见 [LICENSE](LICENSE)。
