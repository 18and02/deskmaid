# DeskMaid 桌面女仆

一只常驻 macOS 桌面的透明立绘女仆:**女仆是壳(脸 + 表情 + 权限 UI,本地、你掌控),Claude 是脑和手(Agent SDK,云端),记忆是单独挂上去的一层(本地加密)。**

> DeskMaid is a transparent desktop maid companion for macOS. The sprite shell, permission UI, and encrypted memory live locally; Claude (via the Agent SDK) is the brain. Run it from source with a Python venv and your own Anthropic API key — no packaged app or notarization required.

## 能做什么

- 点击立绘对话(多行输入 / 拖附件),思考流浮窗可看她的推理过程
- Calendar / Reminders 读写,Mail 读信、建草稿、附件,发送永远人工确认
- 桌面桥接:打开 App / URL、窗口聚焦、剪贴板、粘贴文字、按键
- 长期记忆:本地加密落盘,可查看 / 编辑 / 单条删除,支持自然语言"忘掉刚才那事"
- 预算硬闸:单轮 + 日 / 周成本上限、闲时降频、按工具风险分层配额
- 饥饿系统:预算用到 80% / 95% / 100% 时她会变饿、讨食、罢工,额度重置后满血报喜(台词全本地脚本,不消耗额度)
- 自动免打扰:全屏 / 会议 / 共享 / 录屏 / 摄像头占用 / 系统 Focus 自动静音,共享场景可自动隐藏立绘
- 隐私边界:密码 / 密钥 / 证件号等高敏内容默认拒传云端,拦截时给出解释和一键改写

## 环境要求

- macOS(Apple Silicon 实测通过;Intel 依赖 pip 自动选择对应架构的依赖,未实测)
- Python 3.11+
- 一个 Anthropic API key

## 安装与运行

```bash
git clone <repo-url> deskmaid
cd deskmaid
python3.11 -m venv .venv   # 必须 3.11+;macOS 自带的 python3 往往是 3.9,先用 python3 --version 确认
.venv/bin/pip install -r requirements.txt
cp .env.example .env       # 编辑 .env,填入你的 ANTHROPIC_API_KEY(或留空,首次运行引导里填)
.venv/bin/python Maid/main.py
```

> 没有 3.11+ 的话,用 [uv](https://docs.astral.sh/uv/)(`uv python install 3.11`)或 Homebrew(`brew install python@3.11`)装一个。

首次运行会有引导:API key、称呼、预算档位、数据边界确认。

### 系统权限(TCC)

从源码运行时,自动化(Calendar / Reminders / Mail / System Events)、辅助功能等权限会授予**你启动它的终端**(或 Python 解释器),而不是某个 .app。首次触发对应功能时 macOS 会弹授权;也可以随时从右键菜单的「权限自检」查看哪些就绪、哪些缺失,并跟随恢复向导补授权。

## 自定义立绘

立绘包是目录 + `manifest.json` 的形式,内置的 `petdex-maid-codex` 包(AI 生成)已映射全部语义状态(含饥饿系统的讨食 / 虚弱 / 庆祝形态)。想换自己的立绘:

1. 设置环境变量 `MAID_SPRITE_PACKS_DIR` 指向你的包目录,或直接放进 `Maid/assets/packs/`
2. 参考 `my-maid` 模板(首次使用会自动生成说明)准备各状态的图,缺的状态会逐级降级,最少只需要一张 `idle`
3. 在右键菜单的立绘面板里切换

## 开发

```bash
.venv/bin/pip install -r requirements-dev.txt   # 美术处理 / 打包工具链
./dev_checks.py          # 日常回归(权限自检 + 桌面输入回归)
./dev_checks.py list     # 查看全部回归 profile
```

想打包成 .app(可选,日常使用不需要):见 `build_macos_app.py` 与技术方案 §10。

## 文档

| 文档 | 内容 |
|---|---|
| [使用手册](DeskMaid-使用手册.md) | 安装、日常使用、权限、常见问题 |
| [文档索引](桌面女仆项目-00-文档索引.md) | 三份设计文档的阅读顺序与当前进度 |
| [技术方案](桌面女仆项目-技术方案-macOS版.md) | 架构、四层分工、隐私边界、Backlog(权威) |

## 隐私说明

记忆、预算账本、偏好全部留在本地;你主动发起的对话内容与被允许送出的工具结果会发往 Anthropic API。密码 / 密钥 / Token / 证件号等高敏内容默认拒传。详见技术方案 §14 与首次运行引导里的数据边界确认。

## 许可

代码与内置立绘包(AI 生成)均以 [MIT 许可](LICENSE) 提供。
