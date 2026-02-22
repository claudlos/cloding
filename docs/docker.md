# Docker Mode

When you run Claude Code, it has full access to your machine — your files, your terminal, your `.env`, your SSH keys, everything. It's an LLM agent with root-level power.

**Docker mode puts it in a box.** The model can only touch the workspace you mount and nothing else. It can't read your secrets, wreck your system, or do anything outside the container.

::: warning
Containers still have outbound network access — this is needed for API calls to OpenRouter.
:::

## Setup

Build the Docker image (one-time):

```bash
cloding docker build
```

## Usage

```bash
cloding docker shell                    # Interactive session
cloding docker run "fix the bug"        # Run a prompt
cloding docker run -m haiku "prompt"    # Specific model
cloding docker run -w ./myproject       # Mount workspace
```

Your workspace gets mounted read-write at `/workspace` inside the container. That's the only thing the model can touch.

## Resource Limits

Control how much CPU and memory the container can use:

```bash
cloding docker run --memory 4g --cpus 2 "refactor the auth module"
```

## Container Management

```bash
cloding docker status    # Show running containers
cloding docker stop      # Stop all containers
cloding docker clean     # Remove stopped containers
```

## Security Model

Docker mode provides these security boundaries:

- **Non-root user** inside the container
- **No access** to host filesystem (except mounted workspace)
- **No access** to your SSH keys, `.env` files, or secrets
- **Resource-limited** CPU and memory
- **Outbound network** only (for API calls)

This won't stop a determined attacker, but it prevents the most common accident: an LLM agent accidentally (or intentionally) reading files it shouldn't or running destructive commands on your host system.
