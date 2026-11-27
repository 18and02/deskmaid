# DeskMaid Desktop Companion

A transparent illustrated maid companion that stays on the macOS desktop. **The maid is the shell (face, expressions, and permission UI, local and under your control); Claude is the brain and hands (Agent SDK, cloud); memory is a separate layer (encrypted locally).**

> DeskMaid is a transparent desktop maid companion for macOS. The sprite shell, permission UI, and encrypted memory live locally; Claude (via the Agent SDK) is the brain. Run it from source with a Python venv and your own Anthropic API key — no packaged app or notarization required.

## Features

- Click the character to chat (multiline input and file attachments); a floating thinking stream displays the reasoning process.
- Read and write Calendar and Reminders; read Mail, create drafts, and handle attachments. Sending always requires human confirmation.
- Desktop controls: open apps and URLs, focus windows, use the clipboard, paste text, and send keystrokes.
- Long-term memory is stored encrypted locally. You can view, edit, or delete individual items, and say “forget what just happened” in natural language.
- Hard budget limits per turn and per day/week, reduced activity when idle, and risk-based quotas for tools.
- Hunger system: at 80%, 95%, and 100% of the budget, the character becomes hungry, begs, and goes on strike; when the allowance resets, she celebrates at full energy. These lines are local scripts and do not consume allowance.
- Automatic do-not-disturb: full-screen mode, meetings, sharing, screen recording, camera use, and system Focus automatically mute the companion; the character can also hide during sharing.
- Privacy boundaries: highly sensitive content such as passwords, keys, and ID numbers is blocked from cloud transmission by default, with an explanation and one-click rewrite.

## Requirements

- macOS (tested on Apple Silicon; on Intel, pip selects architecture-specific dependencies automatically, but Intel has not been tested)
- Python 3.11+
- An Anthropic API key

## Download the app (recommended; no Python environment needed)

1. Download the latest `DeskMaid.zip` from [Releases](https://github.com/18and02/deskmaid/releases), extract it, and drag `Deskmaid.app` into Applications.
2. **On first launch, macOS will block the app** because it has not been notarized by Apple. Double-click it, then open **System Settings → Privacy & Security** and click **Open Anyway** near the bottom. macOS will not block it again afterward.
3. Enter your Anthropic API key in the first-run setup.

> This packaged app supports Apple Silicon (M-series) only. On Intel Macs, use the source instructions below.

## Run from source

```bash
git clone https://github.com/18and02/deskmaid.git deskmaid
cd deskmaid
python3.11 -m venv .venv   # 3.11+ is required; macOS's bundled python3 is often 3.9, so check with python3 --version first
.venv/bin/pip install -r requirements.txt
cp .env.example .env       # edit .env and set ANTHROPIC_API_KEY, or leave it blank and enter it during first-run setup
.venv/bin/python Maid/main.py
```

> If you do not have Python 3.11+, install it with [uv](https://docs.astral.sh/uv/) (`uv python install 3.11`) or Homebrew (`brew install python@3.11`).

First-run setup asks for an API key, preferred form of address, budget tier, and confirmation of data boundaries.

### System permissions (TCC)

When launched from source, permissions for automation (Calendar, Reminders, Mail, and System Events), Accessibility, and related features are granted to the **terminal you launched it from** (or to the Python interpreter), not to an `.app`. macOS prompts for permission when a feature is first used. You can also choose **Permission Check** from the right-click menu to see which permissions are ready or missing, then follow the recovery guide to grant them.

## Custom character art

Sprite packs use a directory plus `manifest.json`. The bundled `petdex-maid-codex` pack (AI-generated) maps all semantic states, including begging, weakness, and celebration states from the hunger system. To use your own art:

1. Set `MAID_SPRITE_PACKS_DIR` to your pack directory, or place the pack in `Maid/assets/packs/`.
2. Follow the `my-maid` template (instructions are generated on first use) to prepare images for each state. Missing states fall back through a hierarchy; only one `idle` image is required.
3. Switch packs in the sprite panel from the right-click menu.

## Models and providers (multiple LLMs)

The default provider is the official Anthropic API. DeepSeek and Kimi (Moonshot) offer Anthropic-compatible endpoints, so you can switch providers while keeping the same engine, tools, MCP, and budgets. Open **Models / Providers** from the right-click menu:

1. Choose a provider (Anthropic / DeepSeek / Kimi / Custom).
2. Enter that provider's API key. Keys are stored in the macOS Keychain and kept separately for each provider; you can also use `DEEPSEEK_API_KEY` or `MOONSHOT_API_KEY` environment variables.
3. Set **Current model** to any model ID from that provider. Third-party model names change, so the field is editable.
4. For **Custom**, enter any Anthropic-compatible `base_url` and model ID (for a self-hosted relay or gateway).

Switching restarts the conversation session. If a conversation is in progress, the app will ask you to switch later.

> ⚠️ **Privacy:** When you switch to a third-party provider, conversation context and memory are sent to that provider's endpoint instead of Anthropic.
>
> ⚠️ **Cost reporting:** The budget and hunger system uses usage reported by the CLI. Third-party models are not in its pricing table, so **the dollar amount may be inaccurate** (usually overstated). Budget limits still constrain call count and usage, but do not treat the displayed dollar amount as the actual cost. Third-party models may identify themselves as Claude or GPT because of their training data; this is normal. The selected provider is the source of truth for the model's actual identity.
>
> The native OpenAI API is not compatible with the Anthropic protocol. To use it, connect a conversion proxy (such as claude-code-router or LiteLLM) pointing locally; this is not built in.

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt   # art-processing and packaging toolchain
./dev_checks.py          # routine regression checks (permission self-check + desktop input regression)
./dev_checks.py list     # list all regression profiles
```

Packaging as an `.app` is optional and not needed for everyday use. See `build_macos_app.py` and section 10 of the technical plan.

## Documentation

| Document | Contents |
| --- | --- |
| [User guide](DeskMaid-使用手册.md) | Installation, everyday use, permissions, and FAQ |
| [Documentation index](桌面女仆项目-00-文档索引.md) | Reading order and current status of the three design documents |
| [Technical plan](桌面女仆项目-技术方案-macOS版.md) | Architecture, four-layer responsibilities, privacy boundaries, and authoritative backlog |

## Privacy

Memory, the budget ledger, and preferences stay local. Conversation content you send and tool results you permit may be sent to the Anthropic API (or the third-party provider selected under **Models / Providers**). Highly sensitive content such as passwords, keys, tokens, and ID numbers is blocked from transmission by default. See section 14 of the technical plan and the data-boundary confirmation in first-run setup.

## License

The code and bundled sprite pack (AI-generated) are provided under the [MIT License](LICENSE).

## Attribution

qlmeng2023 — collaborator
