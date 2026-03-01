# Installation

## Standalone Binary (recommended)

Download a single binary — no Node.js required:

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/claudlos/cloding/master/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/claudlos/cloding/master/install.ps1 | iex
```

The installer automatically detects your OS and architecture, downloads the latest release, and adds it to your PATH.

## npm

If you already have Node.js 18+:

```bash
npm i -g cloding
```

## Set up CLI tools

After installing cloding, run the setup command to detect and install all supported CLI tools:

```bash
cloding setup
```

This checks for prerequisites (Node.js, Python, Docker) and installs any missing CLI tools:

- **Claude Code** — via native installer
- **Gemini CLI** — via npm
- **Codex CLI** — via npm
- **GitHub Copilot CLI** — via npm
- **OpenCode** — via npm

::: tip
Run `cloding setup --check` to see what's installed without making any changes.
:::

## Set your API key

```bash
export OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

To make this permanent, add it to your shell profile:

```bash
# ~/.bashrc, ~/.zshrc, or equivalent
export OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

## Verify installation

```bash
cloding --list-models
```

This should display all available models with their pricing. If it works, you're ready to go.

## Optional: Docker

If you want to use [Docker mode](/docker) for sandboxed execution:

- **Docker Desktop** — [Mac](https://docs.docker.com/desktop/setup/install/mac-install/) · [Windows](https://docs.docker.com/desktop/setup/install/windows-install/) · [Linux](https://docs.docker.com/desktop/setup/install/linux/)
- Or **Docker Engine** — [Install guide](https://docs.docker.com/engine/install)

## Optional: Pipeline Mode

For [pipeline mode](/pipeline), you also need:

- **Python 3.11+**

```bash
cd pipeline && pip install -e .
```
