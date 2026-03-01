# Troubleshooting

If you encounter issues while using Cloding, try these common solutions.

## Docker Mode Issues

### Memory Limits Exceeded
When running heavy repositories in Docker, the default memory limit of `2g` (2 Gigabytes) might not be enough, leading to out-of-memory errors or the container silently crashing.

**Solution:** Increase the memory limit using the `--memory` flag.
```bash
cloding docker run --memory 4g "fix the build script"
```

### Docker Daemon Not Running
If you receive an error stating `Docker not found` or `Could not list containers. Is Docker running?`, Docker isn't starting correctly on your host machine.

**Solution:** Start Docker Desktop (or the Docker daemon on Linux). Make sure Docker is running and your user has permissions to interact with it.

### Leftover Orphaned Containers
Occasionally, if a process forcefully exits, stopping routines may fail leaving orphaned containers.

**Solution:** Manually clean containers up using:
```bash
cloding docker clean
```

---

## Tool Launch Issues

### OpenRouter Authentication Errors
If Claude complains about an invalid `x-api-key` format, the fallback mechanism failed.

**Solution:** Ensure `OPENROUTER_API_KEY` is exported correctly in your environment or global config.
```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
```

### "Command not found" for CLI Tools
`cloding` uses native tools (like `copilot` or `codex`). If they aren't installed, `cloding` cannot launch them.

**Solution:** Run the setup command to automatically detect and install missing tools via npm.
```bash
cloding setup
```

## Global Configuration

You can avoid repeatedly setting `OPENROUTER_API_KEY` by adding it once to a `~/.clodingrc` file in your home directory:

```bash
# ~/.clodingrc
OPENROUTER_API_KEY="sk-or-v1-your-key-here"
CLODING_DEFAULT_MODEL="sonnet"
```
