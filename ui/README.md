# Customer Manager Web UI

This desktop-only chat UI is adapted from `<另一个本地项目>/app/static/chat.html`.

It uses the local Hermes customer manager profile:

```text
./.hermes-customer-manager
```

## Run

```bash
cd "."
./run-customer-manager-ui.sh
```

Open:

```text
http://127.0.0.1:8787/chat
```

## How To Test

1. Chat as a loan customer in the main panel.
2. Every 3 to 5 turns, click `更新风控画像`.
3. The right drawer shows the current Markdown profile.
4. The profile is saved to:

```text
./customer-risk-profile.md
```

This is a self-test UI. It talks to the Hermes TUI Gateway and consumes the same event stream used by the Ink TUI, including reasoning, tool progress, tool completion, and inline diff events.
