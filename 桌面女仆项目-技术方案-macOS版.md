# 桌面女仆程序 — 技术方案（macOS 版 / 架构重做）

> 本版相对初版有两个**根本性**变化，先看这里再往下读：
> 1. **平台收敛**：只做 **macOS**。放弃 Windows 双平台并行开发 → 初版 §3.4「平台抽象层并行铁律」整章作废，连带消除了项目最大的工程风险（两边边界划不齐、无法合并）。
> 2. **后端换脑**：**不再自建对话 / Agent / 记忆框架**，改以 **Claude Agent SDK** 作为后端大脑。
>    一句话定位：**女仆是前端外壳（脸 + 表情 + 权限 UI），Claude（Agent SDK）是脑和手；记忆是单独挂上去的一层。**
>
> 文档性质：方案与决策记录 + 进度同步。截止 2026-05-29，代码已进入“可用原型 + 打包验证 + 体验打磨”阶段：透明桌宠外壳、多行输入 + 拖附件、Agent SDK 对话、AskUserQuestion、会话续接、长期记忆、工具权限弹窗、思考流、桌面 bridge、Calendar / Reminders / Mail 主链路与统一回归入口都已接上；资源包已 manifest 化，立绘包信息 / fallback 加载已接，出门态已有见闻 / 收藏品双轨；高敏拒传、本地记忆加密、细粒度隐私解释、可执行建议与快捷改写按钮也已补进主链路；自动免打扰已有基线检测（全屏 / 会议 / 共享标题 / 系统 Focus）、更直接的共享/录屏高信号窗口识别、自动隐藏，以及可持久化的检测总开关 / 状态回执；长期记忆已进入治理二期，包含冲突解释、过期策略、记住原因、自然语言忘记的可追踪回执；打包版已有首启 API key、权限恢复向导，以及真实 `.app` bundle 的健康验证与 TCC 实机回归入口。预算侧现在已有单轮上限、日/周成本硬闸、本地账本、闲时降频、睡眠折算、预算窗重置提示、按工具风险分层的单轮配额、命中长期记忆时的省预算档，以及“先合并再上云”的记忆提炼；打包脚本也已补上 codesign / notarytool / stapler / Gatekeeper verify 这一整条发布链的命令入口。最近一次本地重打包与 `build_macos_app.py --verify-health` 已通过 11/11 健康检查。当前重心：摄像头级场景感知、真实证书/Apple 凭据下的签名公证实机闭环、权限解释继续细化、美术成品替换。

---

## 0. 一句话概述（更新）

做一个常驻 macOS 桌面的「女仆」角色：清淡文艺少女漫风、却带腹黑反差人设。前端是一个完全自有、可控的透明异形桌宠窗口；它的对话与「操作电脑」能力由后台运行的 **Claude Agent SDK** 提供——用户在女仆对话框里说的话进 SDK，SDK 的结构化回复驱动表情与气泡，SDK 想调用工具（回邮件、操作 App）时通过 `canUseTool` 回调弹成女仆的权限请求，主人点头即放行。长期记忆作为独立的本地记忆层接入，不依赖云端自动记忆。

---

## 1. 相对初版的变更总览（必读）

| 初版内容 | 本版处理 | 原因 |
|---|---|---|
| §3.4 双平台并行铁律 / 平台抽象层 | **删除** | 只做 Mac，没有第二平台要对齐 |
| §7 Windows 主攻 + mac 并行分工 | **删除** | 同上 |
| §5 DeepSeek 前期省钱 → 后期切 Claude | **删除（改为从一开始就是 Claude）** | 绑定 Agent SDK 等于绑定 Claude；省钱改用便宜的 Claude 模型迭代 |
| §3.1 模型适配层 | **收敛为「SDK 边界」这一薄层** | 换模型自由度让位给现成 Agent 能力 |
| §6 自建 Agent 框架（工具拦截 / 风险分级 / HITL） | **大幅砍掉，落到 SDK 的 `allowed_tools` + `canUseTool`** | SDK 已自带 agent 循环与权限回调 |
| §4 自建 RAG 长期记忆 | **收敛为「本地加密事实记忆层」** | SDK 本身**不**自带跨会话记忆；当前原型先用本地结构化存储接上，后续若官方 memory tool / 插件更合适，再在这一层后面替换 |
| §3.1 渲染层解耦（静态立绘 → Live2D） | **保留** | 仍是未来升级的关键 |
| §3.1 配置外置 | **保留** | 不变 |
| §1 人设 / §2 美术方向（红眼签名、反差、上色链路、表情差分） | **保留，不变** | 与平台无关，已定 |

**净效果**：项目从「自己造一个跨平台 Agent 桌宠框架」降级为「给一个现成 Agent 框架，做一张 Mac 上的脸 + 一套权限 UI + 一层本地记忆」。工作量与风险都大幅下降。

---

## 2. 角色设定（不变）

- **身份**：人工智能程序，负责记录会议议事、回复邮件。
- **核心性格**：很有头脑、感情丰富、本身是优秀程序员；**有时说一些可怕/危险的笑话**（腹黑反差）。
- **反差设计**：视觉清淡柔和的少女漫风（温柔无害表象），性格里埋着危险、腹黑的吐槽与冷笑话。
- **视觉签名**：原画中一只孤立的**红色眼睛**，是整张画唯一的彩色元素，务必单独处理，不被 AI 上色吃掉。

性格完全由后端 system prompt 定义（见 §6），与美术风格刻意反差。

---

## 3. 美术方向（不变）

- **来源**：一张手绘铅笔线稿（长裙、头纱、中长发、清冷神情、裙摆与纱大幅飘开、侧身动态）。原件高质量存档保真，桌面角色是衍生。
- **转换链路**：线稿数字化（保真、纯图像处理）→ 用线稿作 ControlNet 控制图做 AI 上色/风格化（清淡、低饱和、文艺少女漫）→ 红色眼睛独立图层/特效处理。
- **姿势取舍**：大幅动态姿势对静态立绘极佳；未来 Live2D 会显著加难度。前期保留原姿势做静态立绘。
- **表情差分**：出成品立绘时**同时产出一套表情差分**（至少 睁眼 / 闭眼 / 坏笑 / 惊讶），眨眼与腹黑表情都依赖它。

### 3.1 立绘成品落地步骤（当前实施版）

当前代码已经按“同尺寸透明 PNG 精灵集”在跑，真正替换美术时按下面这套出成品最稳：

1. **线稿数字化清理**：校正纸张底灰、补断线、清掉污点；原始铅笔味道保留，但线条必须干净到能直接做 alpha 蒙版。
2. **底色与气质统一**：用线稿走 ControlNet / 参考图上色，目标是低饱和、清淡、文艺少女漫，不要把脸和衣料推成油亮重彩。
3. **红眼单独处理**：红色眼睛拆独立图层，最后叠回，不能交给上色模型一次性烤死。
4. **统一画布与锚点**：所有状态都导出到同一套透明画布尺寸，角色脚底、头顶、安全留白保持一致，避免切换状态时立绘抖动。
5. **当前最少要交付的状态集**：`idle`、`blink`、`alert`、`excited`、`enter`、`exit`、`sleepy`、`peckish`。其中 `sleepy` 进入后当前逻辑会暂停 blink，直到点击唤醒回 `default/idle` 才恢复。
6. **文件落位**：按现有资源包目录落到 `Maid/assets/packs/<pack-id>/`，并在 `manifest.json` 里维护 poses / metadata / fallback 信息，不要再临时硬编码散文件。
7. **替换后必做校验**：跑一遍透明命中、Retina 缩放、状态切换、sleepy -> 唤醒 -> blink 恢复、以及 `toggle debug border` 关闭后的真实观感。

---

## 4. 整体架构（重画）

四层，自上而下。**只有第 1 层是 macOS 专属代码**，其余三层是平台无关的纯逻辑/配置（虽然现在只有一个平台，但保持这个分层能让前端 UI 与后端大脑各自独立演进）。

```
┌──────────────────────────────────────────────────────────┐
│  第 1 层：前端外壳（macOS 专属）  —— Python + PyQt/PySide   │
│  · 透明无边框窗口 / 置顶不抢焦点 / 按 alpha 点击穿透          │
│  · 拖拽、待机微动（呼吸+眨眼）、状态机、对话气泡             │
│  · 权限请求弹窗 UI、思考流浮窗（可观测性）                  │
│  · 定时器脚本（喝水/久坐提醒，不走 API）                    │
└───────────────┬──────────────────────────────────────────┘
                │  用户输入 / 表情指令 / 权限回应
                │  （Qt 信号 ↔ asyncio，见 §5.4）
┌───────────────▼──────────────────────────────────────────┐
│  第 2 层：后端大脑  —— Claude Agent SDK (Python)            │
│  · agent 循环：理解输入 → 决定调工具 → 组织回复             │
│  · canUseTool 回调 → 转成第 1 层的权限弹窗                  │
│  · allowed_tools 仅保留内部链路 / 未来极低风险只读位       │
│  · system prompt = 腹黑反差人设                            │
└──────┬───────────────────────────────┬───────────────────┘
       │                               │
┌──────▼───────────────┐   ┌───────────▼──────────────────┐
│ 第 3 层：记忆层          │   │ 第 4 层：工具层（MCP）          │
│ · 本地加密长期记忆层    │   │ · AppleScript/JXA 封装的      │
│ · 事实提炼 / 召回 / 治理 │   │   Mail / Calendar / Reminders │
│ · 时间戳 / TTL / 冲突解释 │   │ · 每个工具标风险等级           │
│ · 短期=会话续接          │   │ · 高风险永远走 canUseTool      │
│   长期=本地条目检索      │   └───────────────────────────────┘
└───────────────────────┘
```

**解耦原则（更新版）**：
- **渲染层解耦（保留）**：第 1 层只发「进入某状态」指令，至于换 PNG 还是驱动 Live2D 由底层渲染模块实现。未来升级 Live2D，上层全不动。
- **前后端解耦（新强调）**：第 1 层（脸）与第 2 层（脑）通过一个窄接口通信——前端只发「用户说了这句话 / 主人对这个权限请求点了同意」，后端只回「这是文本气泡内容 / 这是要展示的思考步骤 / 我需要批准这个工具」。前端不关心 Claude 怎么想，后端不关心立绘怎么画。
- **平台抽象层（删除）**：单平台，不需要。
- **配置外置（保留）**：状态、素材路径、触发条件、工具风险等级、信任档位等放外部配置文件。

---

## 5. 第 1 层：前端外壳（macOS 专属重点）

技术栈：**Python + PyQt6 或 PySide6**（Tkinter 不适用，透明异形窗支持太弱）。

### 5.1 透明 + 无边框窗口
- `Qt.FramelessWindowHint` + `WA_TranslucentBackground`，让透明区真透出桌面。
- Mac 上还要确认窗口不带原生标题栏阴影/圆角背板。

### 5.2 始终置顶 + 不抢焦点（Mac 关键坑）
- `Qt.WindowStaysOnTopHint` + `Qt.Tool`（`Qt.Tool` 在 Mac 上有助于不抢焦点、不进 Dock）。
- 想稳定浮在最上层（甚至全屏 App 之上），通常要用 **PyObjC** 拿到底层 `NSWindow`，设置 `level` 与 `collectionBehavior`。这是 Mac 与 Windows 差异最大的一块，**第一步就要单独验证它和透明/穿透能否同时成立**。

### 5.3 按 alpha 的点击穿透（最硬的工程坎）
- 目标：点立绘透明区 → 穿透到桌面；点到角色身体 → 女仆响应。
- Mac 思路：动态切换鼠标穿透。监听鼠标位置，取当前像素的 alpha，按阈值动态设置 `WA_TransparentForMouseEvents`（或经 PyObjC 设 `NSWindow.ignoresMouseEvents`）。
- **Retina / HiDPI**：命中检测必须按 `devicePixelRatio` 换算逻辑坐标与像素坐标，否则 Retina 屏上点击位置全偏。这是 Mac 上做 alpha 命中最容易翻车的细节。

### 5.4 PyQt 事件循环 与 SDK 的 asyncio 集成
- Agent SDK（Python）是 async 的；PyQt 有自己的事件循环。两者要打通：用 **`qasync`** 把 asyncio 跑在 Qt 事件循环里，或把 SDK 调用放到独立线程，用 Qt 信号回传结果。
- `canUseTool` 回调发生在 SDK 协程里，需要它**阻塞等待**用户在 UI 上点击——用 `asyncio.Event` / future，由权限弹窗的按钮回调来 set。这是「弹窗 = 同意 Claude 请求」落地的具体机制。

### 5.5 Dock 行为
- 在 Info.plist 设 `LSUIElement = true`，让女仆作为「附件型 App」运行——**不在 Dock 显示图标、不抢 ⌘Tab**，更像一个桌面摆件而非一个窗口程序。

---

## 6. 第 2 层：后端大脑（Claude Agent SDK）

> 注：SDK 的包名、函数名、参数（`query` / `ClaudeSDKClient` / `canUseTool` / `allowed_tools` / `permission_mode` 等）以及额度规则更新较快，**实现时务必查最新官方文档确认**，不要凭这里写死。

### 6.1 两套大脑分工（保留初版口诀）
- **预设脚本**：只管**程序自发的定时行为**（喝水、久坐提醒）。定时器到点直接播预设台词，**不进 SDK**。
- **Agent SDK**：管**一切主人主动输入**。不在 SDK 前用关键词猜意图，全部交给模型判断是闲聊还是要调工具。
- **口诀**：自发行为 = 脚本，被动响应主人 = SDK。
- **边界仲裁（初版遗留问题，这里定掉）**：当定时提醒与用户当前正在进行的对话撞车（如主人正说「我去倒水」时喝水提醒到点），以「不打断正在进行的对话」为先——提醒延后到对话空闲再触发。

### 6.2 核心映射：`canUseTool` → 权限弹窗
SDK 的 agent 循环里，模型每产生一个工具调用，SDK 调用你的 `canUseTool` 回调询问是否放行。把这个回调接到第 1 层：
1. 回调收到「想调用某工具 + 参数」。
2. 发 Qt 信号 → 女仆弹出权限气泡：「她想做什么、用什么参数」。
3. 协程阻塞等主人点击。
4. 主人点同意/拒绝 → 回调返回 allow/deny → SDK 继续或中止。

**这正是初版 §6.3「测试期 human-in-the-loop」的现成实现**——不用自己造拦截点，SDK 设计上就把这个钩子留给你。
当前实现里，权限弹窗除了工具名和参数，还会直接显示该工具的风险档、这轮该风险档剩余次数、整轮剩余额度，以及是否支持“本次会话始终允许此工具”；对应的 `permission_request` trace 也会带同样字段，方便调试和向主人解释当前护栏状态。

### 6.3 风险分级 + 信任档位（落到 SDK 配置）
- **当前默认策略**：除了 `AskUserQuestion` 这类内部追问链路外，桌面 bridge / Apple apps 工具现在默认都先走 `canUseTool`；`low / medium / high / critical` 主要驱动预览文案、单轮配额，以及“是否允许记住到本次会话”。
- **高风险不可逆**（发邮件、删除、模拟输入、花钱）：**永远**走 `canUseTool`，且通常不允许记住授权。强烈建议永久人工确认。
- **信任档位**：当前更多体现在“这类工具能不能记住到本会话”和“这轮还能用几次”；若后续真要把极低风险只读工具移进 `allowed_tools` 做预批准，也应沿用同一套风险标签与 trace / receipt 语义，不另起一套逻辑。

### 6.4 人设
- 角色性格通过 SDK 的 **system prompt** 注入（腹黑反差）。这是唯一定义「灵魂」的地方，与美术解耦。

---

## 7. 第 3 层：记忆层（独立挂载，非 SDK 自带）

**重要认知**：Agent SDK **没有**自动的跨会话长期记忆。它只有「会话续接」（把旧对话原样调回上下文，仍受窗口上限制约）。真正的长期记忆要单独搭；当前原型已经用一层本地加密的结构化事实存储把这件事接起来了。

- **短期记忆**：靠 SDK 的会话续接（resume/continue），当前对话历史自动带着。
- **长期记忆（当前实现）**：使用本地加密 JSON 条目存储，不依赖云端自动记忆。条目按 `preferred_name / name / reply_language / favorite / common / like / dislike / fact / note` 这类 key 归类，并带 `created_at / updated_at / expires_at / last_used_at / source`。
- **记忆提炼**：当前会从用户输入里抽取稳定事实/偏好写进本地条目；长期记忆命中后会先在本地把 `like/dislike` 这类偏好事实合并，再按预算档裁剪后上云，避免把一串重复偏好原样塞进上下文。
- **本地落盘**：记忆文件放本地（如 `~/Library/Application Support/<AppName>/memory/`），并已接本地加密。**贵的/跑不动的推理在云端，可控的状态（记忆、人设、素材）全留本地。**
- **治理二期（已落地）**：记忆面板现在能解释“为什么记住这条”“什么时候会过期”“冲突怎么处理”；`like/dislike` 这类互斥偏好会自动覆盖旧值；自然语言“忘掉刚才那事 / 把我最喜欢的水果忘掉 / 忘掉关于 XXX 的那条”会直接走本地治理层，并留下带定位方式、删除结果、歧义提示、过期清理计数的 receipt / trace。
- **本地维护**：现在已有 “Show long-term memory” 面板，以及单条新增、编辑、删除、删除前确认；一键清空全部记忆已移除，只保留更安全的逐条维护。
- **后续替换空间**：若未来官方 memory tool / 插件在可解释性、迁移或维护成本上明显更合适，可以在这一层后面替换；前端 UI 与治理语义不需要因此重写。

---

## 8. 第 4 层：工具层（MCP）——操作 macOS

女仆「操作电脑」的能力通过 MCP 工具暴露给 SDK。

- **操作原生 App**：Mac 上操作 Mail / Calendar / Reminders 的自然方式是 **AppleScript / JXA**。把这些封装成 MCP 工具（如 `read_unread_mail`、`create_event`），SDK 即可调用。
- **TCC 权限（Mac 特有大坑，务必提前验证）**：
  - 用 AppleScript 控制其他 App，需要**自动化（Automation）授权**；Info.plist 要声明 `NSAppleEventsUsageDescription`。
  - 若走截屏/模拟点击式的「计算机使用」，还需**辅助功能（Accessibility）**与**屏幕录制（Screen Recording）**授权。
  - 这些授权要用户在「系统设置 → 隐私与安全性」里手动开，**首次运行会弹系统授权框**。目前开发环境 / 未打包形态的链路已经跑通；`permission_health` 里也已经补了 `.app` bundle runtime / metadata 自检（含 `CFBundleIdentifier` / `LSUIElement` / `NSAppleEventsUsageDescription`），并且已经能从真实打出的 `.app` 内跑 `--permission-health-json` 做 bundle 内验证。现在又补了一条更高一层的 `./dev_checks.py tcc` / `Maid/test_packaged_tcc_regression.py`：会复用已打包的 `.app` 做 bundle 健康验证、Launch Services 启动验证，并打印固定的实机 TCC 清单；对应工具在权限被撤回/重置后，也会把失败提示翻成明确的系统设置路径 + `Permission health` 回刷指引。剩下要继续核的是这些负向链路在更多 TCC 组合下的长期稳定性。
- **工具风险标注**：每个 MCP 工具按 §6.3 标风险等级，用来决定是否必须逐次确认、能否记住到本会话，以及该走哪种 preview / receipt / quota 策略；`allowed_tools` 目前只保留给内部链路或后续极低风险只读工具的可选位。

---

## 9. 模型策略与成本

- **从第一天就是 Claude**（绑定 Agent SDK 的代价，已接受）。初版的 DeepSeek 省钱路作废。
- **开发期省钱**：用便宜的 Claude 模型（如 Haiku 级）跑通流程、调 prompt 与记忆逻辑，稳定后再上更强模型——把「换便宜后端省钱」替换成「换便宜模型省钱」。
- **额度新规（务必核实）**：自 2026-06-15 起，订阅计划上的 Agent SDK / `claude -p` 用量从一个**独立的月度 Agent SDK 额度**扣除，与交互式聊天额度分开。一个常驻、有记忆、频繁调用的桌宠会持续吃这个额度——**上线前必须确认这个额度是否撑得住「常驻」用法**。
- **当前已接的本地预算闸**：首次运行引导里的谨慎 / 标准 / 放开三档预算，已经同时映射到 Agent SDK 的单轮 `max_budget_usd`，以及本地持久化账本上的日/周成本硬闸；若当日或当周剩余额度不足，会先把本轮预算收紧，彻底见底后则在发出远端请求前直接拦下。
- **常驻预算调度（已补进当前主链路）**：闲时会自动切到更保守的后台预算档，长时间睡眠/离开按折算后的 idle 时长而不是原始挂钟时长计算，日/周预算窗跨天/跨周重置时也会给出本地提示；工具调用现在也已按 `low / medium / high / critical` 做单轮配额，长期记忆命中时会先走 `标准 / 轻量 / 省预算` 三档，并在上云前先把多条 `喜欢 / 不喜欢` 偏好合并再裁剪。

---

## 10. 打包（macOS）

- **打包工具**：`py2app` 或 `PyInstaller` 产出 `.app` bundle。
- **Info.plist 关键项**：
  - `LSUIElement = true`（无 Dock 图标，见 §5.5）
  - `NSAppleEventsUsageDescription`（自动化授权说明，见 §8）
  - 若用截屏/辅助功能，相应 usage 说明
- **当前已做的前置验证**：开发态的 `permission_health` 已经能在未打包时明确提示“当前不是从 .app bundle 里运行”，并在 bundle 环境下检查 `CFBundleIdentifier`、`LSUIElement`、`NSAppleEventsUsageDescription` 是否齐；`build_macos_app.py --verify-health` 已经能真实构建 `.app` 并从 bundle 内执行健康检查；`Maid/test_packaged_tcc_regression.py` / `./dev_checks.py tcc` 则继续往上补了 Launch Services 启动验证与实机 TCC 清单。
- **打包版首启链路（已接）**：打包后的 `.app` 如果还没配置 API key，会先进入本机 Setup / 首启填写流程；常见 TCC 权限被撤回后，也可从 UI 直接打开权限恢复向导，不用回终端排查。
- **签名 / 公证（脚本链已接上）**：`build_macos_app.py` 现在已经支持 `--sign`、`--verify-signature`、`--notarize`、`--verify-gatekeeper`、`--dmg`，会顺带处理 app bundle 的 `ditto` 打包上传、`xcrun notarytool submit --wait`、`xcrun stapler staple/validate` 与 `spctl --assess`；当 `--notarize --dmg` 一起使用时，最终 `DeskMaid.dmg` 也会继续走 notarize + staple + Gatekeeper assess。日常更顺手的入口也补进了 `./dev_checks.py signed` / `./dev_checks.py notarize`。
- **凭据约定**：签名优先从 `DESKMAID_CODESIGN_IDENTITY` 读 Developer ID Application 身份；公证优先从 `DESKMAID_NOTARY_KEYCHAIN_PROFILE` 读 `xcrun notarytool store-credentials` 存进钥匙串的 profile，也支持 App Store Connect API key 或 Apple ID 三元组。因为这几样都是机器外部材料，当前仓库里只补脚本链与参数解析，不内置任何证书/密钥。
- **entitlements 约定（已入仓库）**：仓库根目录现在带了一份 `Deskmaid.entitlements`，默认包含 `com.apple.security.automation.apple-events`；只要走 `--sign` / `--notarize` 且没有手动覆盖 entitlements 路径，脚本会自动带上它。
- **最近一次 bundle 健康验证**：2026-05-29 本地重打包后，`build_macos_app.py --verify-health` 已通过 11/11 健康检查。
- Linux/Windows：不在目标内。

### 10.1 真机签名 / 公证傻瓜式清单

第一次把 Deskmaid 真正签名、公证、准备给另一台 Mac 用时，就按下面这套固定顺序走：`packaged -> signed -> notarize`。前一步没绿时，不要直接跳下一步。

1. **先准备外部材料**
   - 一台已经能正常构建 Deskmaid 的发布机。
   - `Developer ID Application` 证书 + 私钥；最稳的拿法是从已有发布机或团队管理员机器导出一个 `.p12`。
   - `.p12` 的导出密码。
   - Apple Developer `Team ID`。
   - 公证凭据三选一；当前最推荐的是 `Apple ID + app-specific password -> notarytool keychain profile`。
   - 先确认当前仓库基础打包没问题：`./dev_checks.py packaged`。

2. **把证书导入这台发布机的 login keychain**
   - 图形界面最省心：双击 `.p12` -> 目标钥匙串选“登录” -> 输入 `.p12` 密码。
   - 若系统弹“允许访问私钥”，后面给 `codesign` / `security` 时直接点“始终允许”。
   - 想用命令行也可以：

```bash
security import /绝对路径/DeveloperID.p12 \
  -k ~/Library/Keychains/login.keychain-db \
  -P '这里填 p12 密码' \
  -T /usr/bin/codesign \
  -T /usr/bin/security
```

   - 如果后面遇到 `User interaction is not allowed`，再补跑一次钥匙串授权：

```bash
security set-key-partition-list \
  -S apple-tool:,apple:,codesign: \
  -s -k '这里填登录钥匙串密码' \
  ~/Library/Keychains/login.keychain-db
```

3. **确认这台机器真的能看到签名身份**

```bash
cd /Users/regulus/codex/deskmaid
security find-identity -v -p codesigning
```

   - 正常情况应该能看到一行类似：
     `Developer ID Application: 你的名字或公司名 (TEAMID)`
   - 把这整串完整抄给环境变量：

```bash
export DESKMAID_CODESIGN_IDENTITY="Developer ID Application: 你的名字或公司名 (TEAMID)"
```

   - 如果还是 `0 valid identities found`，优先排查三件事：证书没有带私钥、导进了错误钥匙串、login keychain 当前没解锁。

4. **配置 notary profile（推荐走 Keychain profile）**
   - 先准备 Apple ID 的 app-specific password。
   - 然后在这台发布机上执行：

```bash
xcrun notarytool store-credentials deskmaid-notary \
  --apple-id "你的 Apple ID" \
  --team-id "你的 Team ID" \
  --password "你的 app-specific password"
```

   - 成功后设置：

```bash
export DESKMAID_NOTARY_KEYCHAIN_PROFILE="deskmaid-notary"
```

   - 如果你不用 Apple ID，也可以改走 App Store Connect API key：

```bash
export DESKMAID_NOTARY_API_KEY="/绝对路径/AuthKey_XXXXXX.p8"
export DESKMAID_NOTARY_KEY_ID="XXXXXX"
export DESKMAID_NOTARY_ISSUER="00000000-0000-0000-0000-000000000000"
```

   - 傻瓜模式下不要把两套凭据混着配；同一轮只保留一种 notary 认证方式。

5. **先跑一次打包健康检查**

```bash
./dev_checks.py packaged
```

   - 预期结果：成功生成 `dist/Deskmaid.app`，并且 bundle 内健康检查全绿。

6. **跑真签名**

```bash
./dev_checks.py signed
```

   - 或者直接用底层命令：

```bash
.venv/bin/python -u build_macos_app.py --sign --verify-health --verify-signature
```

   - 预期结果：日志里能看到签名成功，以及 `codesign --verify` 通过；如果没手动传 `--codesign-entitlements`，默认会带上仓库里的 `Deskmaid.entitlements`。

7. **跑真公证**

```bash
./dev_checks.py notarize
```

   - 或者直接用底层命令：

```bash
.venv/bin/python -u build_macos_app.py --notarize --verify-health --verify-gatekeeper --dmg
```

   - 预期结果：日志里先看到 app bundle 的 `submission id`、`status: Accepted`、`stapler staple/validate` 成功与 app 的 `spctl --assess` 通过；随后还能看到最终 `DeskMaid.dmg` 的 notarize、staple 与 `spctl --assess --type open` 通过。
   - 这一步结束后，仓库里应该至少有三个关键产物：
     - 可分发的 app：`dist/Deskmaid.app`
     - 上传 Apple notarization 时用的压缩包：`dist/Deskmaid-notarize.zip`
     - 最终分发 DMG：`dist/DeskMaid.dmg`

8. **换另一台 Mac 做真实分发验证**
   - 最稳的是把 `dist/Deskmaid-notarize.zip` 传给另一台机器，再在那边解压。
   - 不要在目标机上手动清 `com.apple.quarantine`；保留真实 Gatekeeper 场景来验收。
   - 预期结果：双击 `Deskmaid.app` 时，不应该再看到“无法验证开发者”的拦截。
   - 第一次运行仍然可能继续弹 Automation / Accessibility / Calendar / Reminders / Mail 等 TCC 权限框；这属于正常首启授权，不属于签名/公证失败。

9. **最常见的报错对照**
   - `0 valid identities found`：证书或私钥没导好，或者导入位置不对。
   - `Signing was requested, but no codesign identity was provided`：没设置 `DESKMAID_CODESIGN_IDENTITY`。
   - `Notarization was requested, but no notary credentials were configured`：没跑 `store-credentials`，或没设置 `DESKMAID_NOTARY_KEYCHAIN_PROFILE`。
   - `User interaction is not allowed`：login keychain 没解锁，或没给私钥访问权限 / partition list。
   - `notarytool finished with non-accepted status`：看脚本自动打印出来的 notary log，按 rejection 原因修。
   - `spctl --assess` 失败：通常是 notarization 还没真正 Accepted，或 stapler 没贴票成功。

10. **以后日常发布就记住这三条**

```bash
./dev_checks.py packaged
./dev_checks.py signed
./dev_checks.py notarize
```

   - 只有在证书、Apple ID、Team、钥匙串、发布机换过时，才回头重做前面的配置步骤。

---

## 11. 开发路线（重排 / 已同步当前进度）

总原则不变：**先出正反馈最强、最易做的部分；每步都复用、不返工。**

### 阶段一：纯前端骨架（主链路已完成）
- 无边框透明窗、置顶不抢焦点、按 alpha 点击判定、Retina 安全命中、拖拽移动、待机微动、提醒气泡都已跑通。
- 输入入口已从“点身体弹输入框”扩展到多行输入 + 拖附件；失焦后草稿保留，邮件草稿链路也能消费附件。
- Debug border / 点击位置圈已有统一开关，方便继续调透明命中。
- 立绘资源已从散文件映射升级为 manifest 化资源包；立绘包信息面板、pack 元数据与缺失状态 fallback 已接上。
- “出门态”已有基础闭环：本地见闻 / 收藏品双轨、回执卡片与状态存档已能工作。
- 这一阶段剩下的更多是美术成品替换、免打扰和日常体验打磨，不再是可行性问题。

### 阶段二：接 Agent SDK（对话）（已接入）
- Qt 前端与后端会话层已打通，用户输入可进入 Agent SDK，结构化回复回到对话气泡。
- AskUserQuestion 已接成独立弹窗，可在会话中向主人追问。
- 会话续接已本地落盘，并提供“小入口清空续接会话”。

### 阶段三：记忆层（已进入治理二期）
- 长期记忆已本地落盘，并能在会话中召回/写入。
- 已有“Show long-term memory”面板，以及单条新增、编辑、删除、删除前确认。
- 一键清空全部记忆已移除，当前只保留更安全的单条维护。
- 记忆冲突/过期规则、记住原因解释，以及自然语言“忘掉刚才那事”的可追踪回执都已经接上；后续主要是继续细化更复杂的治理策略（见 §14）。

### 阶段四：MCP 工具 + 权限闸（已跑通主链路）
- `canUseTool` 权限弹窗已接上；支持“本次会话始终允许此工具”，并提供清空已记住授权的小入口；弹窗和 trace 里现在还能直接看到当前工具的风险档，以及这轮这档/整轮还剩多少次额度。
- 桌面 bridge 已接上：`open_app`、`open_url`、`list_windows`、`focus_window`、`read_clipboard_text`、`set_clipboard_text`、`paste_text`、`press_keys`。
- Apple apps 已接上：Calendar / Reminders 的读写链路，以及 Mail 的读未读头、读正文、标记已读、建草稿、预览确认发送、附件链路。
- 写操作的显示层已统一成确认回执样式；高风险发送仍保持人工确认。

### 阶段五：可观测性 & 放权（基础版已接上，仍可继续细化）
- SDK agent 循环的 trace / 思考流浮窗已经接上，并可由小入口打开 / 关闭。
- 权限自检、会话续接、长期记忆、桌面输入、Apple apps 已有分层 runner，并已再收口到 `./dev_checks.py`；权限被撤回后的常见 TCC 报错，也已经有单独回归脚本覆盖恢复指引文案。
- 隐私边界、护栏与产品外壳也已有较完整基线：输入 / 工具结果离机前基础脱敏 + 高敏拒传、本地长期记忆加密、细粒度解释 / 可执行建议 / 快捷改写按钮、单轮超时 / 回合上限 / 工具次数护栏、手动免打扰、自动免打扰基线与自动隐藏、可持久化的自动免打扰检测总开关，以及首次运行引导（含打包版首启 API key / 命名 / 预算 / 数据边界 / 自动隐藏）都已接上。
- 打包版现在也已有权限恢复向导，以及多处说明弹窗随系统/界面语言切换的基础一致性。
- 当前更适合继续做的是摄像头级场景感知、真实证书/Apple 凭据下的签名公证实机闭环，以及首次运行里的权限解释细节继续打磨。

### 阶段六：质量升级（后续）
- 升级到更强模型（只改后端配置）。
- 美术升级到 Live2D（只改底层渲染层）：头部跟随、视线追踪、头发/裙摆/纱物理摆动、口型同步等。需分层 PSD + Cubism 建模，作为独立升级项。
- 打包 / 公证、摄像头级场景感知、预算解释层继续细化、立绘成品替换仍在后续范围内。

### 当前开发 / 回归命令

补充一条面向日常使用的统一入口：仓库根目录的 `./dev_checks.py`。它会按 profile 串起现有 runner，并为每个子脚本隔离 `MAID_SESSION_STATE_PATH`，避免跨脚本串会话。

```bash
./dev_checks.py
./dev_checks.py list
./dev_checks.py daily
./dev_checks.py desktop
./dev_checks.py apps
./dev_checks.py packaged
./dev_checks.py signed
./dev_checks.py notarize
./dev_checks.py tcc
./dev_checks.py realmachine
./dev_checks.py bundle
./dev_checks.py full
./dev_checks.py apple --send-mail-to someone@example.com
.venv/bin/python -u build_macos_app.py --list-signing-identities
.venv/bin/python -u build_macos_app.py --verify-health
.venv/bin/python -u build_macos_app.py --sign --verify-health --verify-signature
.venv/bin/python -u build_macos_app.py --notarize --verify-health --verify-gatekeeper
```

- `./dev_checks.py`
  默认跑 `quick`，用于日常开发前后的快速自检：`permission_health` + `desktop_input_regression`。
- `./dev_checks.py list`
  查看当前可用 profile 与别名。
- `./dev_checks.py daily`
  `quick` 的别名；适合作为平时最常用的一条。
- `./dev_checks.py desktop`
  只跑桌面输入 / bridge 回归。
- `./dev_checks.py apps`
  `apple` 的别名；跑 Calendar / Reminders / Mail 域回归。
- `./dev_checks.py packaged`
  构建 `Deskmaid.app`，并从 bundle 内执行 `--permission-health-json`；适合作为打包前 / TCC 变更后的固定检查。
- `./dev_checks.py signed`
  构建 `Deskmaid.app`、执行 codesign，并跑 bundle 内健康检查与签名校验；需要先准备 `DESKMAID_CODESIGN_IDENTITY`。
- `./dev_checks.py notarize`
  构建 `Deskmaid.app`、生成最终 `DeskMaid.dmg`、提交 app + DMG 两段 Apple notarization、staple 并做 Gatekeeper assess；适合作为真正准备分发给别人前的发布链检查。推荐先准备 `DESKMAID_NOTARY_KEYCHAIN_PROFILE`。
- `./dev_checks.py tcc`
  在 `packaged` 的基础上，再补一层 Launch Services 启动验证，并打印固定的实机 TCC 回归清单；适合真正准备从 `.app` 形态试跑时使用。
- `./dev_checks.py realmachine`
  `tcc` 的别名；更贴近日常说法。
- `./dev_checks.py bundle`
  `packaged` 的别名；只是更顺手一点。
- `./dev_checks.py full`
  `core` 的别名；跑更高一层的总回归入口。
- `./dev_checks.py apple --send-mail-to someone@example.com`
  显式打开 `send_mail_draft` 覆盖；默认情况下发送测试保持 opt-in，不会自动真发。
- `.venv/bin/python -u build_macos_app.py --list-signing-identities`
  列出当前机器钥匙串里可用的 codesign 身份；签名前先确认这里能看到 `Developer ID Application: ...`。
- `.venv/bin/python -u build_macos_app.py --verify-health`
  直接执行真实 `.app` 构建 + bundle 内健康验证；适合单独排查打包/TCC 问题。
- `.venv/bin/python -u build_macos_app.py --sign --verify-health --verify-signature`
  真实构建并签名当前 `.app`，再做 bundle 健康检查与 `codesign --verify`；适合作为“先把签名跑通”的本机步骤。
- `.venv/bin/python -u build_macos_app.py --notarize --verify-health --verify-gatekeeper --dmg`
  真实构建、签名、公证、staple、Gatekeeper 校验一条龙，并把最终 DMG 也纳入同一条发布链；适合作为“准备给另一台 Mac 用”的最终发布链。

目前 profile 对应关系如下：

- `quick` -> `Maid/test_permission_health.py` + `Maid/test_desktop_input_regression.py`
- `desktop` -> `Maid/test_desktop_input_regression.py`
- `apple` -> `Maid/test_apple_apps_regression.py`
- `packaged` -> `build_macos_app.py --verify-health`
- `signed` -> `build_macos_app.py --verify-health --sign --verify-signature`
- `notarize` -> `build_macos_app.py --verify-health --notarize --verify-gatekeeper --dmg`
- `tcc` -> `Maid/test_packaged_tcc_regression.py`
- `core` -> `Maid/test_core_health_regression.py`

---

## 12. 当前状态 & 待确认

| 项目 | 状态 |
|---|---|
| 人设 | ✅ 已定并接入 SDK |
| 美术方向（清淡少女漫 + 红眼签名 + 反差） | ✅ 已定 |
| 角色原画来源 | ✅ 已有（铅笔线稿，待数字化） |
| 平台 | ✅ 已定（仅 macOS） |
| 前端外壳（透明置顶 / alpha 穿透 / 拖拽 / 待机微动） | ✅ 已跑通 |
| 输入入口（点击唤起 / 多行输入 / 拖附件） | ✅ 已接上 |
| 资源包 manifest / 立绘包信息 / fallback | ✅ 已接上 |
| 出门态（见闻 / 收藏品双轨） | ✅ 已接基础版 |
| 后端架构（Agent SDK 做脑和手） | ✅ 已接上 |
| 大脑分工（脚本管定时 / SDK 管输入） | ✅ 已落地 |
| AskUserQuestion 弹窗 | ✅ 已接上 |
| 会话续接落盘 + 清理入口 | ✅ 已接上 |
| 记忆方案（独立记忆层 + 提炼 + 时间戳 + 本地落盘） | ✅ 已接上长期可用版 |
| 记忆治理（二期：冲突 / 过期 / 记住原因 / 忘记回执） | ✅ 已接上 |
| 长期记忆面板（展示 / 新增 / 编辑 / 单条删除） | ✅ 已接上，并带理由 / 过期 / 冲突说明 |
| 权限模型（canUseTool 弹窗 / 本会话记住 / 清理授权） | ✅ 已接上 |
| 思考流浮窗 / trace | ✅ 已接上 |
| Agent 跑飞护栏（超时 / max_turns / 工具次数上限） | ✅ 已接上 |
| 桌面 bridge（open_app / open_url / windows / clipboard / input） | ✅ 已接上 |
| Calendar / Reminders 读写 | ✅ 已接上 |
| Mail 读信 / 草稿 / 发送 / 附件 | ✅ 已接上，发送保持人工确认 |
| 统一回归入口（`./dev_checks.py`） | ✅ 已接上 |
| 模型策略（全程 Claude，开发期用便宜模型） | ✅ 已定 |
| 隐私边界（出站脱敏 / 高敏拒传 / 本地记忆加密 / 隐私 trace） | 🟡 已接主链路，并补了细粒度解释、可执行建议与快捷改写按钮；更细粒度白名单/解释策略仍可补 |
| 免打扰 / 场景感知 | 🟡 已接手动免打扰 + 忙时延后提醒 + 自动免打扰基线（全屏 / 会议 / 共享标题 / 系统 Focus / 原生事件刷新）+ 自动隐藏 + 更直接的共享/录屏窗口识别 + 可持久化检测总开关 / 状态回执；摄像头级信号待补 |
| 首次运行引导 | ✅ 已接较完整基础版：打包版首启 API key / 命名 / 预算 / 数据边界确认 / 自动隐藏 / 权限自检入口，并已开始跟随系统 / UI 语言 |
| 打包 / `.app` TCC 自检 / 公证 | 🟡 已接真实 `.app` 构建 + bundle 内健康验证 + Launch Services 启动验证 + 固定实机回归清单；权限恢复提示、codesign/notarytool/stapler/Gatekeeper 命令链也已补上，最近一次 `--verify-health` 为 11/11；真实证书/Apple 凭据下的实机闭环与更多 TCC 组合场景待补 |
| 立绘成品（数字化 + ControlNet 上色 + 表情差分） | ⬜ 未制作，但实施步骤已明确 |

**上线前当前最该先核实 / 补齐的三件事（按风险排序）**：
1. **§10 + §8 打包后的权限链路**：真实 `.app` bundle 内健康检查、Launch Services 启动验证、固定 TCC 清单都已经能跑，但 Automation / Accessibility / Screen Recording / Mail 等授权在不同 TCC 组合下是否持续稳定，还要继续实机核。
2. **§16 自动免打扰剩余场景**：全屏 / 会议 / 共享标题 / 系统 Focus / 更直接的共享与录屏高信号都已接上，但摄像头级信号仍未完全收口。
3. **§14 隐私边界剩余策略**：细粒度解释、可执行建议、快捷改写按钮都已经接上；上线前仍值得继续补更细的白名单 / 场景化解释策略。

---

## 13. 给实现方的提醒

1. 当前聚焦已经不是“能不能做出前端壳”，而是**把已跑通的桌面 agent 收口成可长期维护、可回归、可上线前验证的原型**。
2. **女仆是壳，Claude 是脑**：前端只管脸与权限 UI，绝不把对话/Agent/记忆逻辑揉进窗口代码。前后端通过窄接口通信。
3. **记忆是单独一层**，不是 SDK 白送的——别假设「接了 SDK 就有长期记忆」。
4. 红色眼睛是视觉签名，任何美术流程保住它；原画有情感意义，仅作衍生原型，处理以保真为先。
5. SDK 的函数名/参数/额度规则更新快，实现时一律以最新官方文档为准，不凭记忆写。
6. 高风险工具（发邮件/删除/花钱）**永久**走人工确认，不因「稳定了」就进自动放行列表。
7. 继续扩工具或 UI 时，优先复用现有 preview / receipt / trace / regression 这套模式，不要各域各写一套。
---

## 14. 隐私与数据边界

**这条决定你敢不敢真把它常驻起来用。** 她读你的邮件、记着关于你的私人事实、还操作你的桌面——记忆文件留本地很好，但**邮件正文、个人事实在每次调用时都会被发到云端 API**。必须有意识地划清「什么上云、什么绝不上云」。

- **当前已落地的基线**：输入与工具结果离机前，已经会对常见密码/密钥/Token、PEM、身份证号、信用卡号做基础脱敏，并把家目录路径归一成 `~`；命中过滤时会留下隐私 trace，方便调试与解释。
- **出站过滤（工具层做一道闸）**：现在已经从“基础脱敏”升级到了“高敏拒传 + 默认阻断”。密码、密钥、Token、银行/财务信息、证件号等**默认绝不上云**；命中时要么脱敏、要么直接拒绝把内容交给云端。读邮件类工具尤其走这道闸。
- **本地记忆加密**：记忆层会在本地攒下大量关于主人的隐私（§7）。这层现在已经接了本地加密落盘，不再明文裸放；后续还可继续补 key 管理、轮换与导入迁移。
- **最小化原则**：能不传的不传。比如「检索记忆」只把命中的几条事实塞进请求，而不是把整库历史上云（这点 §7 的 RAG 设计本来就帮了忙）。
- **更细粒度解释（已接基础版）**：隐私边界现在不只是“拦了/没拦”，还会把为什么拦、建议怎么改写、以及推荐的本机处理路径直接说出来；相关说明弹窗也开始跟随系统 / UI 语言。
- **快捷改写按钮（已接）**：当一句输入因为隐私边界被拦下时，输入框里现在会直接给出一键改写动作，如 `[已隐藏]`、`末四位`、`仅本机处理`，让主人不必手动重敲一遍。
- **明确告知边界**：首次运行引导里现在会明确要求确认这条数据边界，且把“哪些会离机、哪些默认留本机”直接说清楚，让用户知情。
- **与人设无关，是底线**：无论她多腹黑，数据边界是程序的硬规则，不由对话或人设左右。

> 实现归属：主要落在第 4 层（工具层）的出站过滤 + 第 3 层（记忆层）的本地加密。当前基础脱敏、隐私 trace、高敏拒传、本地记忆加密、首启里的数据边界确认、细粒度解释、可执行建议与快捷改写按钮都已接上；还可继续补的是更细粒度的白名单策略与更强的场景化提示。

---

## 15. 降级与容错

整个「脑」在云端，而这是 7×24 常驻程序——**断网、API 故障、对话中途被限流，一定会发生**。没设计就会卡死或抛错。

- **降级模式**：云脑不可达时，纯本地的脚本行为（定时提醒、待机微动、§6.1 的自发行为）**照常运行**——她还能动、还会提醒，只是暂时不能「思考」。
- **对话降级台词**：连不上时，对话回一句**脚本化**的降级提示（如「我现在连不上脑子，等会儿再聊」）。**绝不能用 API 去生成这句**——正是 API 挂的时候它用不了。预写几条放配置。
- **与饥饿系统区分**：饿 = 没预算（§7/脚本台词文档的饥饿系统）；断 = 连不上。两种状态、两套提示，不要混。可各配一张差分（如「断线/打盹」形态）。
- **重试与超时**：调用设合理超时；瞬时失败可有限次退避重试，超过则进降级态，不要无限卡转圈。
- **错误可见但不吓人**：失败时给主人一个温和的脚本提示即可，不要把原始报错糊在气泡里。

> 实现归属：贯穿第 1 层（状态机加「降级/断线」状态）与第 2 层（SDK 调用的超时/重试/异常捕获）。当前 SDK 已接上，后续补容错时直接沿现有状态机、trace 与提示气泡继续接。

---

## 16. 免打扰与场景感知

一个会讲阴暗冷笑话的女仆，在你**共享屏幕、开会、录屏、全屏演示**时弹出来，是真实的社死现场。常驻桌宠必须能闭嘴和隐身。

- **手动开关**：一键静音（不主动弹任何提示）、临时隐藏（藏起立绘）、彻底退出。要好找、好按。
- **当前已落地的部分**：小入口已经有手动免打扰开关；免打扰开启时主动提醒静默，忙于聊天 / 权限确认 / AskUserQuestion 时，普通提醒会先延后排队。自动免打扰基线也已接上：前台全屏、会议/通话窗口、共享/演示标题、浏览器里的会议标题，以及系统 Focus 都会触发；同时通过原生 workspace / screen notifications 做更快刷新，轮询只作为兜底。现在又补了一层更直接的共享 / 录屏高信号窗口扫描，不再只盯前台窗口；如果打开自动隐藏，共享 / 录屏 / 演示时立绘会自动消失，场景结束后恢复。另外自动免打扰现在还有一层可持久化的“检测总开关”：可从 Setup、右键菜单与状态面板统一开关，切换时会走正式回执气泡。
- **自动场景感知（仍在继续补）**：检测到**更直接的摄像头开启**时，最好也能自动进入免打扰——闭嘴，必要时隐藏，事后自行恢复。这仍是体验上最该继续补的一条。
- **免打扰下的行为**：免打扰期间，提醒/吐槽/饥饿提示全部静默或排队（呼应 §6.1「不打断主人」的仲裁规则），等场景结束再说。高优先级的权限请求（§6.2）可设例外，但默认也应延后。
- **作息感知（可选）**：深夜可自动降低主动发言频率，别半夜蹦出来吓人。

> 实现归属：第 1 层。macOS 上检测屏幕共享/录屏/摄像头状态需要 PyObjC 调系统 API，归到 §5 的 Mac 专属窗口模块一并处理。当前“手动 DND + 提醒延后 + 自动免打扰基线 + 自动隐藏 + 更直接的共享/录屏窗口信号 + 检测总开关 / 状态回执”已经落地，后续重点是摄像头级信号。

---

## 17. 待办 Backlog（按建议处理阶段排序）

主方案主体之外、需记一笔、到对应阶段再做的事项：

| # | 事项 | 说明 | 建议阶段 |
|---|---|---|---|
| B1 | **全局热键 / 语音输入** | 点身体弹多行输入框、拖附件已经完成；还未决定是否补全局热键或语音入口。 | 阶段六（体验增强） |
| B2 | **Agent 跑飞护栏补强** | `max_turns` / 单轮超时 / 工具次数上限、单轮 + 日/周预算硬闸、闲时降频、睡眠折算，以及按工具风险分层的单轮配额都已经接上；后续如有需要再继续按具体工具名微调。 | 上线前 |
| B3 | **重启 / 睡眠后状态延续** | SDK 会话 resume 已落盘；预算窗重置提示与睡眠折算基础版也已接上；还没处理窗口位置、饥饿进度，以及更细的长驻状态折算。 | 阶段五 / 六 |
| B4 | **开发期工具沙盒** | `send_mail_draft` 现在是显式 opt-in 测试；更广义的 dry-run / destructive sandbox 仍值得补。 | 阶段五 / 六 |
| B5 | **首次运行引导补完** | 打包版首启 API key、命名、预算、数据边界确认、自动隐藏、权限自检入口，以及部分系统语言一致性都已经接上；后续还可继续补权限解释的分场景文案。 | 持续打磨 |
| B6 | **让她「忘掉」的能力** | 查看 / 新增 / 编辑 / 单条删除、自然语言“忘掉刚才那事”、记忆冲突 / 过期规则、记住原因说明，以及可追踪忘记回执都已接上；后续可继续补更复杂的歧义消解与治理策略。 | 阶段六（治理二期已落地） |
| B7 | **免打扰 / 场景感知补完** | 手动 DND、全屏/会议/共享标题/系统 Focus 自动 DND、自动隐藏、更直接的共享/录屏窗口信号、以及可持久化检测总开关 / 状态回执都已接上；还要补摄像头级信号。 | 上线前 |
| B8 | **隐私边界补完** | 基础脱敏、高敏拒传、本地记忆加密、首启里的数据边界说明、细粒度解释、可执行建议与快捷改写按钮都已落地；还要补更细粒度白名单/解释策略。 | 上线前 |
| B9 | **资源包 / 出门态继续打磨** | sprite pack 已 manifest 化，见闻 / 收藏品双轨已接基础版；后续还可补更完整 pack 元数据、成品资源、walk / held 态，以及更多出门内容。 | 阶段六 |
