#!/usr/bin/env node

/**
 * cloding — Claude Code with any model via OpenRouter.
 *
 * Sets the right env vars and spawns `claude` so you can use
 * Qwen, Haiku, Sonnet, or any OpenRouter model at a fraction of the cost.
 *
 * Usage:
 *   cloding                         # Interactive with default model (Qwen)
 *   cloding -m haiku                # Use a different model
 *   cloding -p "fix the bug"        # Non-interactive single prompt
 *   cloding --list-models           # Show available models
 *   cloding pipeline "Add auth"     # Run the full pipeline
 *   cloding docker build            # Build Docker image
 *   cloding docker run "prompt"     # Run in a Docker container
 */

const { spawn, spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

// ──────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────
const OPENROUTER_BASE_URL = "https://openrouter.ai/api";
const DEFAULT_MODEL = "qwen";
const DOCKER_IMAGE = "cloding:latest";
const DOCKER_NETWORK = "cloding-net";

// Build-time version (set by Bun compile via define; undefined in npm mode)
var CLODING_VERSION;

// ──────────────────────────────────────────────
// Signal forwarding — relay SIGINT/SIGTERM to child processes
// ──────────────────────────────────────────────
function forwardSignals(child) {
  const handler = (signal) => {
    if (child && !child.killed) {
      child.kill(signal);
    }
  };
  process.on("SIGINT", handler);
  process.on("SIGTERM", handler);
  // Clean up listeners when child exits to avoid leaks
  child.on("exit", () => {
    process.removeListener("SIGINT", handler);
    process.removeListener("SIGTERM", handler);
  });
}

// ──────────────────────────────────────────────
// .env loader (no dependencies)
// ──────────────────────────────────────────────
function loadEnvFile() {
  // Search for .env in: cwd, then user home, then cloding package root
  const candidates = [
    path.join(process.cwd(), ".env"),
    path.join(os.homedir(), ".env"),
    path.join(__dirname, "..", ".env"),
  ];

  for (const envPath of candidates) {
    if (fs.existsSync(envPath)) {
      const lines = fs.readFileSync(envPath, "utf8").split("\n");
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) continue;
        const eqIdx = trimmed.indexOf("=");
        if (eqIdx === -1) continue;
        const key = trimmed.slice(0, eqIdx).trim();
        let val = trimmed.slice(eqIdx + 1).trim();
        // Strip surrounding quotes
        if (
          (val.startsWith('"') && val.endsWith('"')) ||
          (val.startsWith("'") && val.endsWith("'"))
        ) {
          val = val.slice(1, -1);
        }
        // Don't override existing env vars (check existence, not truthiness —
        // empty string values like ANTHROPIC_API_KEY="" must be preserved)
        if (!(key in process.env)) {
          process.env[key] = val;
        }
      }
      return envPath;
    }
  }
  return null;
}

// ──────────────────────────────────────────────
// Model registry
// ──────────────────────────────────────────────
function loadModels() {
  let models;
  try {
    // require() works in both Node.js (resolves relative to __dirname) and
    // Bun-compiled binaries (inlined at build time).
    models = require("../models.json");
  } catch {
    console.error("Error: Could not load models.json");
    process.exit(1);
  }

  // Validate structure
  if (!models || typeof models !== "object" || Array.isArray(models)) {
    console.error("Error: models.json must be a JSON object");
    process.exit(1);
  }
  for (const [shortcut, m] of Object.entries(models)) {
    if (typeof m.id !== "string") {
      console.error(`Error: models.json: "${shortcut}" missing required "id" (string)`);
      process.exit(1);
    }
    if (!m.name || typeof m.name !== "string") {
      console.error(`Error: models.json: "${shortcut}" missing required "name" (string)`);
      process.exit(1);
    }
    if (typeof m.in !== "number" || typeof m.out !== "number") {
      console.error(`Error: models.json: "${shortcut}" requires numeric "in" and "out" costs`);
      process.exit(1);
    }
  }

  return models;
}

// ──────────────────────────────────────────────
// Arg parsing (lightweight, no dependencies)
// ──────────────────────────────────────────────
function parseArgs(argv) {
  const args = {
    model: null,
    prompt: null,
    listModels: false,
    version: false,
    help: false,
    setup: false,
    setupArgs: [],
    pipeline: false,
    pipelineArgs: [],
    docker: false,
    dockerSubcommand: null,
    dockerArgs: [],
    claudeArgs: [], // passthrough args for claude CLI
  };

  let i = 0;
  while (i < argv.length) {
    const arg = argv[i];

    if (arg === "setup") {
      args.setup = true;
      args.setupArgs = argv.slice(i + 1);
      break;
    }

    if (arg === "pipeline") {
      args.pipeline = true;
      args.pipelineArgs = argv.slice(i + 1);
      break;
    }

    if (arg === "docker") {
      args.docker = true;
      args.dockerSubcommand = argv[i + 1] || "help";
      args.dockerArgs = argv.slice(i + 2);
      break;
    }

    switch (arg) {
      case "-m":
      case "--model":
        if (i + 1 >= argv.length) {
          console.error("Error: --model requires a value.\n  Usage: cloding -m <model>");
          process.exit(1);
        }
        args.model = argv[++i];
        break;
      case "-p":
      case "--prompt":
        if (i + 1 >= argv.length) {
          console.error("Error: --prompt requires a value.\n  Usage: cloding -p \"your prompt\"");
          process.exit(1);
        }
        args.prompt = argv[++i];
        break;
      case "--list-models":
        args.listModels = true;
        break;
      case "-v":
      case "--version":
        args.version = true;
        break;
      case "-h":
      case "--help":
        args.help = true;
        break;
      default:
        args.claudeArgs.push(arg);
        break;
    }
    i++;
  }

  return args;
}

// ──────────────────────────────────────────────
// Display helpers
// ──────────────────────────────────────────────
function printVersion() {
  // In Bun-compiled binary, CLODING_VERSION is set at build time via define
  if (typeof CLODING_VERSION !== "undefined") {
    console.log(`cloding v${CLODING_VERSION}`);
    return;
  }
  // npm-installed version: read from package.json on disk
  try {
    const pkg = JSON.parse(
      fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8")
    );
    console.log(`cloding v${pkg.version}`);
  } catch {
    console.log("cloding (unknown version)");
  }
}

function printHelp() {
  console.log(`
cloding — Claude Code with any model via OpenRouter

USAGE:
  cloding                            Interactive session (default: Qwen)
  cloding -m haiku                   Use a specific model
  cloding -p "fix the bug"           Non-interactive single prompt
  cloding --list-models              Show available models and costs
  cloding setup                      Detect and install all CLI tools
  cloding pipeline "Add auth"        Run the full pipeline (requires Python)
  cloding docker <command>           Docker container management

OPTIONS:
  -m, --model <name|id>   Model shortcut or full OpenRouter model ID
  -p, --prompt <text>     Run non-interactively with a single prompt
      --list-models       Show available models with pricing
  -v, --version           Show version
  -h, --help              Show this help

SETUP COMMANDS:
  cloding setup                      Check status and install missing CLI tools
  cloding setup --check              Check status only (no installation)
  cloding setup --force              Reinstall all CLI tools

DOCKER COMMANDS:
  cloding docker build               Build the cloding Docker image
  cloding docker run "prompt"         Run a prompt in a container
  cloding docker shell                Interactive claude session in a container
  cloding docker status               Show running cloding containers
  cloding docker stop                 Stop all cloding containers
  cloding docker clean                Remove stopped cloding containers
  cloding docker help                 Show Docker help

MODELS (shortcuts):
  qwen       Qwen 3 Coder        $0.12/$0.75 per Mtok  (default, ~42x cheaper)
  haiku      Claude Haiku 4.5     $1.00/$5.00 per Mtok
  sonnet     Claude Sonnet 4      $3.00/$15.00 per Mtok
  opus       Claude Opus 4.6      $5.00/$25.00 per Mtok
  deepseek   DeepSeek V3.2        $0.26/$0.38 per Mtok
  gemini     Gemini 2.5 Pro       $1.25/$10.00 per Mtok
  copilot    GitHub Copilot       $0 (subscription)

  Or pass any OpenRouter model ID:
    cloding -m meta-llama/llama-4-scout

ENVIRONMENT:
  OPENROUTER_API_KEY       Required. Your OpenRouter API key.
  CLODING_DEFAULT_MODEL    Optional. Default model shortcut (default: qwen).

EXAMPLES:
  cloding                            # Start coding with Qwen ($0.12/Mtok)
  cloding -m haiku                   # Quick task with Haiku
  cloding -m opus -p "Review arch"   # One-shot with Opus
  cloding docker build               # Build Docker image first
  cloding docker run "Fix the bug"   # Run isolated in Docker
  cloding docker shell               # Interactive Docker session
  cloding pipeline "Add auth" -c configs/qwen-fanout.yaml

All other arguments are passed through to claude.
`);
}

function printModels(models) {
  console.log("\nAvailable models:\n");
  console.log(
    "  Shortcut    Model                    Input $/Mtok   Output $/Mtok  vs Opus"
  );
  console.log(
    "  ─────────── ──────────────────────── ────────────── ────────────── ───────"
  );

  // Opus cost for comparison
  const opusOut = models.opus ? models.opus.out : 75.0;

  for (const [shortcut, m] of Object.entries(models)) {
    const savings = m.out > 0 ? Math.round(opusOut / m.out) : 0;
    const savingsStr =
      shortcut === "opus" ? "    baseline" :
      savings > 0 ? `    ${savings}x cheaper` : "    n/a";
    console.log(
      `  ${shortcut.padEnd(11)} ${m.name.padEnd(24)} $${m.in.toFixed(2).padStart(6)}         $${m.out.toFixed(2).padStart(6)}${savingsStr}`
    );
  }

  console.log(
    "\n  Use: cloding -m <shortcut>   or   cloding -m <openrouter-model-id>\n"
  );
}

// ──────────────────────────────────────────────
// Resolve model to OpenRouter model ID
// ──────────────────────────────────────────────
function resolveModel(modelArg, models) {
  if (!modelArg) {
    // Use default from env, or fall back to qwen
    const defaultModel = process.env.CLODING_DEFAULT_MODEL || DEFAULT_MODEL;
    return resolveModel(defaultModel, models);
  }

  // Check shortcuts first
  if (models[modelArg.toLowerCase()]) {
    return models[modelArg.toLowerCase()];
  }

  // Assume it's a full OpenRouter model ID (e.g. "meta-llama/llama-4-scout")
  return {
    id: modelArg,
    name: modelArg,
    in: 0,
    out: 0,
    provider: "openrouter",
    api_key_env: "OPENROUTER_API_KEY",
    description: "Custom model",
  };
}

function canUseCliLinkedAuth(tool) {
  return tool === "gemini" || tool === "copilot";
}

function normalizeGeminiModelForLinkedAuth(modelId) {
  // OpenRouter-style IDs like "google/gemini-2.5-pro" are not valid in
  // account-linked Gemini CLI mode. Use the provider model name instead.
  if (typeof modelId !== "string") return modelId;
  const slash = modelId.indexOf("/");
  if (slash > 0 && slash < modelId.length - 1) {
    return modelId.slice(slash + 1);
  }
  return modelId;
}

function hasArg(args, flag) {
  return Array.isArray(args) && args.includes(flag);
}

function getNodeMajorVersion() {
  const major = Number.parseInt((process.versions.node || "0").split(".")[0], 10);
  return Number.isNaN(major) ? 0 : major;
}

function dockerAvailable() {
  try {
    const result = spawnSync("docker", ["--version"], { stdio: "ignore" });
    return result.status === 0;
  } catch {
    return false;
  }
}

// ──────────────────────────────────────────────
// Setup command — detect and install CLI tools
// ──────────────────────────────────────────────
function commandExists(cmd) {
  const isWin = process.platform === "win32";
  try {
    const result = spawnSync(isWin ? "where" : "which", [cmd], {
      stdio: "ignore",
      timeout: 5000,
    });
    return result.status === 0;
  } catch {
    return false;
  }
}

function getCommandVersion(cmd, versionFlag) {
  try {
    const result = spawnSync(cmd, [versionFlag || "--version"], {
      encoding: "utf8",
      timeout: 10000,
      stdio: ["ignore", "pipe", "pipe"],
    });
    if (result.status === 0) {
      const out = (result.stdout || result.stderr || "").trim();
      return out.split("\n")[0].slice(0, 80);
    }
    return null;
  } catch {
    return null;
  }
}

function askConfirm(question) {
  return new Promise((resolve) => {
    const readline = require("readline");
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });
    rl.question(`${question} [Y/n] `, (answer) => {
      rl.close();
      const a = (answer || "y").trim().toLowerCase();
      resolve(a === "y" || a === "yes" || a === "");
    });
  });
}

function detectTools() {
  const platform = process.platform;

  const tools = [
    // ── Prerequisites (detect only, print hints) ──
    {
      name: "node",
      category: "prerequisite",
      displayName: "Node.js",
      cmd: "node",
      installMethod: null,
      installHint: {
        darwin: "brew install node  OR  https://nodejs.org",
        linux: "curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash - && sudo apt-get install -y nodejs",
        win32: "winget install OpenJS.NodeJS  OR  https://nodejs.org",
      },
    },
    {
      name: "python",
      category: "prerequisite",
      displayName: "Python 3.11+",
      cmd: platform === "win32" ? "python" : "python3",
      installMethod: null,
      installHint: {
        darwin: "brew install python@3.12  OR  https://python.org",
        linux: "sudo apt install python3  OR  https://python.org",
        win32: "winget install Python.Python.3.12  OR  https://python.org",
      },
    },
    {
      name: "docker",
      category: "prerequisite",
      displayName: "Docker",
      cmd: "docker",
      installMethod: null,
      installHint: {
        darwin: "brew install --cask docker  OR  https://docs.docker.com/get-docker/",
        linux: "https://docs.docker.com/engine/install/",
        win32: "winget install Docker.DockerDesktop  OR  https://docs.docker.com/get-docker/",
      },
    },
    // ── CLI Tools (detect + install) ──
    {
      name: "claude",
      category: "cli",
      displayName: "Claude Code",
      cmd: "claude",
      installMethod: "native",
      installCmd: {
        darwin: ["bash", ["-c", "curl -fsSL https://claude.ai/install.sh | bash"]],
        linux: ["bash", ["-c", "curl -fsSL https://claude.ai/install.sh | bash"]],
        win32: ["powershell", ["-NoProfile", "-Command", "irm https://claude.ai/install.ps1 | iex"]],
      },
    },
    {
      name: "gemini",
      category: "cli",
      displayName: "Gemini CLI",
      cmd: "gemini",
      installMethod: "npm",
      npmPackage: "@google/gemini-cli",
    },
    {
      name: "codex",
      category: "cli",
      displayName: "Codex CLI",
      cmd: "codex",
      installMethod: "npm",
      npmPackage: "@openai/codex",
    },
    {
      name: "copilot",
      category: "cli",
      displayName: "GitHub Copilot CLI",
      cmd: "copilot",
      installMethod: "npm",
      npmPackage: "@github/copilot",
    },
    {
      name: "opencode",
      category: "cli",
      displayName: "OpenCode",
      cmd: "opencode",
      installMethod: "npm",
      npmPackage: "opencode-ai",
    },
  ];

  return tools.map((t) => {
    const installed = commandExists(t.cmd);
    return {
      ...t,
      installed,
      versionStr: installed ? getCommandVersion(t.cmd) : null,
    };
  });
}

function printSetupStatus(tools) {
  console.log("\n\x1b[36m⚡ cloding setup\x1b[0m — Tool Status\n");

  const prerequisites = tools.filter((t) => t.category === "prerequisite");
  const cliTools = tools.filter((t) => t.category === "cli");

  console.log("  \x1b[1mPrerequisites:\x1b[0m");
  for (const t of prerequisites) {
    const icon = t.installed ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m";
    const ver = t.installed && t.versionStr ? `  \x1b[2m${t.versionStr}\x1b[0m` : "";
    console.log(`    ${icon} ${t.displayName}${ver}`);
  }

  console.log("\n  \x1b[1mCLI Tools:\x1b[0m");
  for (const t of cliTools) {
    const icon = t.installed ? "\x1b[32m✓\x1b[0m" : "\x1b[33m○\x1b[0m";
    const ver = t.installed && t.versionStr ? `  \x1b[2m${t.versionStr}\x1b[0m` : "";
    console.log(`    ${icon} ${t.displayName}${ver}`);
  }
  console.log("");
}

function installNpmPackage(pkg) {
  const isWin = process.platform === "win32";
  console.log(`    Running: npm install -g ${pkg}`);
  const result = spawnSync("npm", ["install", "-g", pkg], {
    stdio: "inherit",
    shell: isWin,
    timeout: 120000,
  });
  return result.status === 0;
}

function installTool(tool) {
  const platform = process.platform;

  if (tool.installMethod === "native") {
    const cmd = tool.installCmd[platform];
    if (!cmd) {
      console.log(`    \x1b[33m!\x1b[0m No native installer for ${platform}`);
      return false;
    }
    console.log(`    Running native installer for ${tool.displayName}...`);
    const result = spawnSync(cmd[0], cmd[1], {
      stdio: "inherit",
      timeout: 120000,
    });
    return result.status === 0;
  }

  if (tool.installMethod === "npm") {
    return installNpmPackage(tool.npmPackage);
  }

  return false;
}

async function handleSetup(args) {
  const force = args.setupArgs.includes("--force");
  const checkOnly = args.setupArgs.includes("--check");

  // Detect all tools
  const tools = detectTools();

  // Print current status
  printSetupStatus(tools);

  // For prerequisites that are missing, print install hints
  const missingPrereqs = tools.filter((t) => t.category === "prerequisite" && !t.installed);
  if (missingPrereqs.length > 0) {
    const platform = process.platform;
    console.log("  \x1b[1mMissing prerequisites\x1b[0m (install manually):");
    for (const t of missingPrereqs) {
      const hint = t.installHint[platform] || t.installHint.linux;
      console.log(`    ${t.displayName}: ${hint}`);
    }
    console.log("");
  }

  if (checkOnly) {
    const installed = tools.filter((t) => t.installed).length;
    const total = tools.length;
    console.log(`  ${installed}/${total} tools detected.\n`);
    process.exit(0);
  }

  // Determine which CLI tools to install
  const toInstall = tools.filter((t) => {
    if (t.category !== "cli") return false;
    if (force) return true;
    return !t.installed;
  });

  if (toInstall.length === 0) {
    console.log("  \x1b[32mAll CLI tools are already installed!\x1b[0m\n");
    process.exit(0);
  }

  // List what will be installed
  console.log(`  Will ${force ? "reinstall" : "install"} ${toInstall.length} tool(s):`);
  for (const t of toInstall) {
    const method = t.installMethod === "native" ? "native installer" : `npm: ${t.npmPackage}`;
    console.log(`    - ${t.displayName}  (${method})`);
  }
  console.log("");

  // Ask for confirmation
  const confirmed = await askConfirm("  Proceed with installation?");
  if (!confirmed) {
    console.log("  Cancelled.\n");
    process.exit(0);
  }
  console.log("");

  // Install each tool
  let succeeded = 0;
  let failed = 0;
  for (const tool of toInstall) {
    console.log(`  Installing ${tool.displayName}...`);
    const ok = installTool(tool);
    if (ok) {
      console.log(`    \x1b[32m✓\x1b[0m ${tool.displayName} installed successfully\n`);
      succeeded++;
    } else {
      console.log(`    \x1b[31m✗\x1b[0m ${tool.displayName} installation failed\n`);
      failed++;
    }
  }

  console.log(
    `  Done: \x1b[32m${succeeded} installed\x1b[0m` +
    (failed > 0 ? `, \x1b[31m${failed} failed\x1b[0m` : "") +
    "\n"
  );
  process.exit(failed > 0 ? 1 : 0);
}

function dockerImageExists() {
  try {
    const result = spawnSync("docker", ["images", "-q", DOCKER_IMAGE], {
      encoding: "utf8",
    });
    return (result.stdout || "").trim().length > 0;
  } catch {
    return false;
  }
}

function getDockerfilePath() {
  // Check relative to package: pipeline/docker/Dockerfile
  const bundled = path.join(__dirname, "..", "pipeline", "docker");
  if (fs.existsSync(path.join(bundled, "Dockerfile"))) {
    return bundled;
  }
  // Check cwd
  const cwdDocker = path.join(process.cwd(), "pipeline", "docker");
  if (fs.existsSync(path.join(cwdDocker, "Dockerfile"))) {
    return cwdDocker;
  }
  return null;
}

function ensureNetwork() {
  try {
    // Safe: constant network name, no user input. Uses spawnSync for safety.
    spawnSync("docker", ["network", "create", DOCKER_NETWORK], { stdio: "ignore" });
    // Ignore errors — network may already exist
  } catch {
    // Network already exists, that's fine
  }
}

function printDockerHelp() {
  console.log(`
cloding docker — Run Claude Code in isolated Docker containers

COMMANDS:
  cloding docker build                         Build the cloding Docker image
  cloding docker run "your prompt here"        Run a prompt in a fresh container
  cloding docker run -m haiku "prompt"         Run with a specific model
  cloding docker shell                         Interactive claude session in Docker
  cloding docker shell -m sonnet               Interactive with specific model
  cloding docker status                        Show running cloding containers
  cloding docker stop                          Stop all running cloding containers
  cloding docker clean                         Remove all stopped cloding containers
  cloding docker help                          Show this help

OPTIONS (for run/shell):
  -m, --model <name>       Model shortcut or OpenRouter ID (default: qwen)
  -p, --prompt <text>      Prompt text (alternative to positional argument)
  -w, --workspace <path>   Mount a local directory as /workspace (default: cwd)
  --memory <limit>         Container memory limit (default: 2g)
  --cpus <limit>           Container CPU limit (default: 1.0)
  --name <name>            Custom container name
  --no-rm                  Don't auto-remove container on exit

EXAMPLES:
  cloding docker build
  cloding docker run "Add error handling to src/api.js"
  cloding docker run -m haiku -w ./myproject "Fix the tests"
  cloding docker shell -w /home/user/code
  cloding docker status
  cloding docker stop

NOTES:
  - Each container gets its own isolated environment
  - Workspace is mounted at /workspace inside the container
  - Containers auto-remove on exit (use --no-rm to keep them)
  - Containers run as non-root user 'coder' for security
  - Resource limits: 2GB RAM, 1 CPU core (configurable)
`);
}

function dockerBuild() {
  const dockerDir = getDockerfilePath();
  if (!dockerDir) {
    console.error(
      "Error: Dockerfile not found.\n\n" +
        "Docker mode requires the full repository (not the npm package).\n" +
        "  git clone https://github.com/claudlos/cloding\n" +
        "  cd cloding && cloding docker build\n"
    );
    process.exit(1);
  }

  console.log(`\x1b[36m⚡ cloding\x1b[0m Building Docker image: ${DOCKER_IMAGE}`);
  console.log(`  Dockerfile: ${path.join(dockerDir, "Dockerfile")}\n`);

  const child = spawn("docker", ["build", "-t", DOCKER_IMAGE, dockerDir], {
    stdio: "inherit",
  });
  forwardSignals(child);

  child.on("exit", (code) => {
    if (code === 0) {
      console.log(
        `\n\x1b[32m✓ Image ${DOCKER_IMAGE} built successfully!\x1b[0m`
      );
      console.log("  Run: cloding docker shell");
      console.log('  Run: cloding docker run "your prompt here"\n');
    } else {
      console.error(`\n\x1b[31m✗ Build failed (exit code ${code})\x1b[0m`);
    }
    process.exit(code ?? 0);
  });

  child.on("error", (err) => {
    console.error(`Error: ${err.message}`);
    process.exit(1);
  });
}

function dockerRun(dockerArgs, models, interactive) {
  // Parse docker run/shell args
  let modelArg = null;
  let workspace = process.cwd();
  let memory = "2g";
  let cpus = "1.0";
  let containerName = null;
  let autoRemove = true;
  let prompt = null;
  const extraClaudeArgs = [];
  const modelShortcuts = new Set(Object.keys(models).map((m) => m.toLowerCase()));

  let i = 0;
  while (i < dockerArgs.length) {
    const arg = dockerArgs[i];
    switch (arg) {
      case "-m":
      case "--model":
        if (i + 1 >= dockerArgs.length) { console.error("Error: --model requires a value."); process.exit(1); }
        modelArg = dockerArgs[++i];
        break;
      case "-p":
      case "--prompt":
        if (i + 1 >= dockerArgs.length) { console.error("Error: --prompt requires a value."); process.exit(1); }
        prompt = dockerArgs[++i];
        break;
      case "-w":
      case "--workspace":
        if (i + 1 >= dockerArgs.length) { console.error("Error: --workspace requires a path."); process.exit(1); }
        workspace = path.resolve(dockerArgs[++i]);
        break;
      case "--memory":
        if (i + 1 >= dockerArgs.length) { console.error("Error: --memory requires a value (e.g. 2g)."); process.exit(1); }
        memory = dockerArgs[++i];
        break;
      case "--cpus":
        if (i + 1 >= dockerArgs.length) { console.error("Error: --cpus requires a value (e.g. 1.0)."); process.exit(1); }
        cpus = dockerArgs[++i];
        break;
      case "--name":
        if (i + 1 >= dockerArgs.length) { console.error("Error: --name requires a value."); process.exit(1); }
        containerName = dockerArgs[++i];
        break;
      case "--no-rm":
        autoRemove = false;
        break;
      default:
        // In docker run mode:
        // - first bare token can be an implicit model shortcut (e.g. "codex-5")
        // - next bare token is treated as prompt
        if (!interactive && !arg.startsWith("-")) {
          const isKnownModel = modelShortcuts.has(arg.toLowerCase());
          if (!modelArg && !prompt && isKnownModel) {
            modelArg = arg;
          } else if (!prompt) {
            prompt = arg;
          } else {
            extraClaudeArgs.push(arg);
          }
        } else {
          extraClaudeArgs.push(arg);
        }
        break;
    }
    i++;
  }

  // Validate
  if (!interactive && !prompt) {
    const modelHint = modelArg
      ? "\nDid you mean:\n" +
        `  cloding docker run -m ${modelArg} "your prompt here"\n` +
        `  cloding docker shell -m ${modelArg}\n`
      : "";
    console.error(
      'Error: No prompt provided.\n\n' +
        '  Usage: cloding docker run "your prompt here"\n' +
        modelHint
    );
    process.exit(1);
  }

  if (!dockerImageExists()) {
    console.error(
      `Error: Docker image '${DOCKER_IMAGE}' not found.\n\n` +
        "  Build it first: cloding docker build\n"
    );
    process.exit(1);
  }

  // Resolve model
  const model = resolveModel(modelArg, models);
  const tool = model.tool || "claude";
  const isPlanProvider = model.provider === "plan";
  const apiKeyEnv = model.api_key_env || "OPENROUTER_API_KEY";
  const apiKey = isPlanProvider ? "" : process.env[apiKeyEnv];
  const usingLinkedCliAuth = !apiKey && canUseCliLinkedAuth(tool);
  if (!apiKey && !usingLinkedCliAuth && !isPlanProvider) {
    if (apiKeyEnv === "OPENROUTER_API_KEY") {
      console.error(
        "Error: OPENROUTER_API_KEY not set.\n\n" +
          "Get your key at https://openrouter.ai/keys\n" +
          "Then: export OPENROUTER_API_KEY=sk-or-v1-...\n"
      );
    } else {
      console.error(
        `Error: ${apiKeyEnv} not set.\n\n` +
          `Please set it: export ${apiKeyEnv}=...`
      );
    }
    process.exit(1);
  }

  // Block plan-mode tools in Docker: subscription auth (OAuth tokens, system
  // credential stores) cannot be passed into containers. Suggest alternatives.
  if (isPlanProvider) {
    const altLines = [];
    if (tool === "claude") {
      const base = modelArg.replace(/-p$/, "");
      altLines.push(
        `  Use API key mode:     cloding docker run -m ${base}-a "..."`,
        `    Requires: export ANTHROPIC_API_KEY=...`,
        `  Use OpenRouter:       cloding docker run -m ${base} "..."`,
        `    Requires: export OPENROUTER_API_KEY=...`
      );
    } else if (tool === "codex") {
      altLines.push(
        `  Use API key mode:     cloding docker run -m codex-5-a "..."`,
        `    Requires: export OPENAI_API_KEY=...`
      );
    } else if (tool === "gemini") {
      altLines.push(
        `  Use API key mode:     cloding docker run -m gemini-3-a "..."`,
        `    Requires: export GOOGLE_API_KEY=...`
      );
    }
    altLines.push(
      `  Run without Docker:   cloding -m ${modelArg} "..."`
    );
    console.error(
      `Error: Plan/subscription mode (${modelArg}) cannot authenticate inside Docker.\n\n` +
        `Subscription auth tokens are stored on your host (system credential\n` +
        `store, browser sessions, etc.) and cannot be passed into containers.\n\n` +
        `Alternatives:\n` +
        altLines.join("\n") +
        "\n"
    );
    process.exit(1);
  }

  // Validate workspace exists and is a directory
  if (!fs.existsSync(workspace)) {
    console.error(`Error: Workspace not found: ${workspace}`);
    process.exit(1);
  }
  if (!fs.statSync(workspace).isDirectory()) {
    console.error(`Error: Workspace path is not a directory: ${workspace}`);
    process.exit(1);
  }

  // Ensure network exists
  ensureNetwork();

  // Generate container name if not provided
  if (!containerName) {
    const suffix = Date.now().toString(36);
    containerName = `cloding-${interactive ? "shell" : "run"}-${suffix}`;
  }

  // Write env vars to a temp file so secrets don't leak via process args.
  // Set only what the selected tool/provider needs.
  const envVars = [];
  if (tool === "claude") {
    const provider = model.provider || "openrouter";
    if (provider === "plan") {
      // Paid plan: only set model, let Claude use its built-in auth
      envVars.push(`ANTHROPIC_MODEL=${model.id}`);
    } else if (provider === "anthropic") {
      // Direct Anthropic API key
      envVars.push(
        `ANTHROPIC_API_KEY=${apiKey}`,
        `ANTHROPIC_MODEL=${model.id}`
      );
    } else {
      // OpenRouter (default)
      // Auth goes through ANTHROPIC_AUTH_TOKEN (Bearer token).
      // IMPORTANT: ANTHROPIC_API_KEY must be empty string, NOT the real key.
      // The Anthropic SDK sends ANTHROPIC_API_KEY as an x-api-key header,
      // and OpenRouter treats any non-empty x-api-key as requesting the
      // Anthropic provider specifically — which fails for non-Anthropic
      // models (qwen, deepseek, gemini, etc).
      // Setting it to "" sends an empty x-api-key header that OpenRouter
      // ignores, falling back to Bearer auth which routes correctly.
      envVars.push(
        `ANTHROPIC_BASE_URL=${OPENROUTER_BASE_URL}`,
        `ANTHROPIC_AUTH_TOKEN=${apiKey}`,
        `ANTHROPIC_API_KEY=`,
        `ANTHROPIC_MODEL=${model.id}`
      );
    }
  } else if (tool === "gemini") {
    if (apiKey) {
      if (model.provider === "openrouter") {
        envVars.push(`GEMINI_API_KEY=${apiKey}`);
      } else {
        envVars.push(`GOOGLE_API_KEY=${apiKey}`, `GEMINI_API_KEY=${apiKey}`);
      }
    }
  } else if (tool === "opencode" && apiKey) {
    envVars.push(`OPENCODE_API_KEY=${apiKey}`);
  } else if (tool === "codex") {
    if (apiKey) envVars.push(`OPENAI_API_KEY=${apiKey}`);
  } else if (tool === "copilot" && apiKey) {
    envVars.push(`GITHUB_TOKEN=${apiKey}`);
  }
  const envFileContent = envVars.join("\n") + "\n";
  const envFilePath = path.join(os.tmpdir(), `cloding-env-${Date.now()}.tmp`);
  fs.writeFileSync(envFilePath, envFileContent, { mode: 0o600 });

  // Build docker command — uses spawn with argument array (safe, no shell injection)
  const cmd = ["docker", "run"];

  if (interactive) {
    cmd.push("-it");
  } else if (prompt) {
    // Allocate tty for one-shot mode so tool output streams visibly
    cmd.push("-t");
  }

  if (autoRemove) {
    cmd.push("--rm");
  }

  cmd.push(
    "--name", containerName,
    "--network", DOCKER_NETWORK,
    "--memory", memory,
    "--cpus", cpus,
    "-v", `${workspace.replace(/\\/g, "/")}:/workspace`,
    "--env-file", envFilePath
  );

  // Mount host's ~/.claude.json (settings only, not credentials) so Claude Code
  // has consistent config in Docker. We do NOT mount ~/.claude/.credentials.json
  // because OAuth tokens would override our OpenRouter env vars.
  if (tool === "claude") {
    const homeDir = os.homedir();
    const claudeJson = path.join(homeDir, ".claude.json");
    if (fs.existsSync(claudeJson)) {
      const jsonPath = claudeJson.replace(/\\/g, "/");
      cmd.push("-v", `${jsonPath}:/home/coder/.claude.json:ro`);
    }
  }

  if (tool !== "claude") {
    // Map tool name to entrypoint binary/script
    let entrypoint;
    if (tool === "codex") {
      // Codex needs a wrapper that runs `codex login --with-api-key` first
      entrypoint = "/usr/local/bin/codex-entrypoint.sh";
    } else if (tool === "copilot") {
      entrypoint = "copilot";
    } else {
      entrypoint = tool;
    }
    cmd.push("--entrypoint", entrypoint);
  }

  cmd.push(DOCKER_IMAGE);

  // Add tool-specific args
  if (!interactive && prompt) {
    if (tool === "claude" || tool === "gemini" || tool === "copilot") {
      cmd.push("-p", prompt);
    } else if (tool === "opencode") {
      cmd.push("run", prompt);
    } else if (tool === "codex") {
      cmd.push("exec", prompt);
    }
  }

  if (tool === "gemini") {
    if (model.id) cmd.push("--model", model.id);
  } else if (tool === "opencode" && model.id) {
    cmd.push("--model", model.id);
  } else if (tool === "codex") {
    if (model.id) cmd.push("--model", model.id);
    if (!interactive && prompt) cmd.push("--full-auto");
    if (!interactive && prompt && !hasArg(extraClaudeArgs, "--skip-git-repo-check")) {
      cmd.push("--skip-git-repo-check");
    }
  }

  cmd.push(...extraClaudeArgs);

  // Print banner
  const costInfo =
    model.in > 0 ? ` ($${model.in}/$${model.out} per Mtok)` : "";
  console.log(
    `\x1b[36m⚡ cloding docker\x1b[0m → ${model.name}${costInfo}`
  );
  console.log(`  Tool: ${tool}`);
  console.log(`  Container: ${containerName}`);
  console.log(`  Workspace: ${workspace} → /workspace`);
  console.log(`  Resources: ${memory} RAM, ${cpus} CPUs`);

  if (model.in > 0 && model.out > 0 && models.opus) {
    const savings = Math.round(models.opus.out / model.out);
    if (savings > 1) {
      console.log(`  \x1b[32m${savings}x cheaper than Opus\x1b[0m`);
    }
  }
  if (usingLinkedCliAuth) {
    console.log(
      `  \x1b[33mNote:\x1b[0m ${apiKeyEnv} not set. Using existing ${tool} CLI account session.`
    );
  }
  console.log("");

  // Clean up env file on exit (contains API key)
  function cleanupEnvFile() {
    try { fs.unlinkSync(envFilePath); } catch {}
  }

  // Spawn docker — uses argument array (no shell interpretation)
  const child = spawn(cmd[0], cmd.slice(1), {
    stdio: "inherit",
  });

  // Signal handlers: clean up env file and forward signal to child
  const cleanupAndForward = (signal) => {
    cleanupEnvFile();
    if (child && !child.killed) {
      child.kill(signal);
    }
  };
  process.on("SIGINT", () => cleanupAndForward("SIGINT"));
  process.on("SIGTERM", () => cleanupAndForward("SIGTERM"));

  child.on("exit", (code) => {
    process.removeAllListeners("SIGINT");
    process.removeAllListeners("SIGTERM");
    cleanupEnvFile();
    if (code && code !== 0) {
      console.error(`\n\x1b[31mContainer exited with code ${code}\x1b[0m`);
      console.error(`Tip: Run with --no-rm to inspect logs: docker logs <container>`);
    }
    process.exit(code ?? 0);
  });
  child.on("error", (err) => {
    process.removeAllListeners("SIGINT");
    process.removeAllListeners("SIGTERM");
    cleanupEnvFile();
    console.error(`Error launching Docker: ${err.message}`);
    console.error("Make sure Docker is installed and running.");
    process.exit(1);
  });
}

function dockerStatus() {
  console.log("\x1b[36m⚡ cloding\x1b[0m Running containers:\n");

  try {
    // Safe: uses spawnSync with argument array, no shell injection possible
    const result = spawnSync(
      "docker",
      ["ps", "--filter", "name=cloding", "--format", "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"],
      { encoding: "utf8" }
    );

    if (result.stdout && result.stdout.trim()) {
      console.log(result.stdout);
    } else {
      console.log("  No running cloding containers.\n");
      console.log("  Start one with:");
      console.log('    cloding docker run "your prompt"');
      console.log("    cloding docker shell\n");
    }
  } catch {
    console.error(
      "Error: Could not list containers. Is Docker running?"
    );
    process.exit(1);
  }
}

function dockerStop() {
  console.log("\x1b[36m⚡ cloding\x1b[0m Stopping all cloding containers...\n");

  try {
    // Safe: uses spawnSync with argument array
    const result = spawnSync(
      "docker",
      ["ps", "-q", "--filter", "name=cloding"],
      { encoding: "utf8" }
    );

    const ids = (result.stdout || "")
      .trim()
      .split("\n")
      .filter((id) => id);

    if (ids.length === 0) {
      console.log("  No running cloding containers to stop.\n");
      return;
    }

    for (const id of ids) {
      try {
        const inspect = spawnSync(
          "docker", ["inspect", "--format", "{{.Name}}", id],
          { encoding: "utf8" }
        );
        const name = (inspect.stdout || id).trim().replace(/^\//, "");

        spawnSync(
          "docker", ["stop", "-t", "5", id],
          { stdio: "ignore" }
        );
        console.log(`  \x1b[32m✓\x1b[0m Stopped: ${name}`);
      } catch {
        console.log(`  \x1b[31m✗\x1b[0m Failed to stop: ${id}`);
      }
    }
    console.log(`\n  Stopped ${ids.length} container(s).\n`);
  } catch {
    console.error("Error: Could not stop containers. Is Docker running?");
    process.exit(1);
  }
}

function dockerClean() {
  console.log(
    "\x1b[36m⚡ cloding\x1b[0m Cleaning up stopped cloding containers...\n"
  );

  try {
    // Safe: uses spawnSync with argument array
    const result = spawnSync(
      "docker",
      ["ps", "-aq", "--filter", "name=cloding", "--filter", "status=exited"],
      { encoding: "utf8" }
    );

    const ids = (result.stdout || "")
      .trim()
      .split("\n")
      .filter((id) => id);

    if (ids.length === 0) {
      console.log("  No stopped cloding containers to clean.\n");
      return;
    }

    for (const id of ids) {
      try {
        const inspect = spawnSync(
          "docker", ["inspect", "--format", "{{.Name}}", id],
          { encoding: "utf8" }
        );
        const name = (inspect.stdout || id).trim().replace(/^\//, "");

        spawnSync(
          "docker", ["rm", id],
          { stdio: "ignore" }
        );
        console.log(`  \x1b[32m✓\x1b[0m Removed: ${name}`);
      } catch {
        console.log(`  \x1b[31m✗\x1b[0m Failed to remove: ${id}`);
      }
    }
    console.log(`\n  Cleaned ${ids.length} container(s).\n`);
  } catch {
    console.error(
      "Error: Could not clean containers. Is Docker running?"
    );
    process.exit(1);
  }
}

// ──────────────────────────────────────────────
// Docker dispatcher
// ──────────────────────────────────────────────
function handleDocker(args) {
  if (!dockerAvailable()) {
    console.error(
      "Error: Docker not found.\n\n" +
        "Install Docker Desktop:\n" +
        "  https://docs.docker.com/get-docker/\n"
    );
    process.exit(1);
  }

  const models = loadModels();

  switch (args.dockerSubcommand) {
    case "build":
      dockerBuild();
      break;
    case "run":
      dockerRun(args.dockerArgs, models, false);
      break;
    case "shell":
      dockerRun(args.dockerArgs, models, true);
      break;
    case "status":
    case "ps":
      dockerStatus();
      break;
    case "stop":
      dockerStop();
      break;
    case "clean":
    case "cleanup":
    case "prune":
      dockerClean();
      break;
    case "help":
    case "--help":
    case "-h":
      printDockerHelp();
      break;
    default:
      console.error(
        `Unknown docker command: ${args.dockerSubcommand}\n`
      );
      printDockerHelp();
      process.exit(1);
  }
}

// ──────────────────────────────────────────────
// Main
// ──────────────────────────────────────────────
function main() {
  // Load .env
  loadEnvFile();

  // Parse args (skip node and script path)
  const args = parseArgs(process.argv.slice(2));

  if (args.version) {
    printVersion();
    process.exit(0);
  }

  if (args.help) {
    printHelp();
    process.exit(0);
  }

  const models = loadModels();

  if (args.listModels) {
    printModels(models);
    process.exit(0);
  }

  // ── Setup mode ──
  if (args.setup) {
    handleSetup(args);
    return;
  }

  // ── Docker mode ──
  if (args.docker) {
    handleDocker(args);
    return;
  }

  // ── Pipeline mode ──
  // Delegated early so --dry-run works without an API key
  if (args.pipeline) {
    const pipelineDir = path.join(__dirname, "..", "pipeline");
    if (!fs.existsSync(pipelineDir)) {
      console.error(
        "Error: Pipeline not found.\n\n" +
          "Pipeline mode requires the full repository (not the npm package).\n" +
          "  git clone https://github.com/claudlos/cloding\n" +
          "  cd cloding/pipeline && pip install -e .\n"
      );
      process.exit(1);
    }

    const pythonArgs = ["-m", "cloding", ...args.pipelineArgs];
    console.log(`Running pipeline: python ${pythonArgs.join(" ")}`);

    // Pipeline inherits env but needs CLAUDECODE stripped.
    // API key may be absent for --dry-run; Python side validates when needed.
    const pipelineEnv = { ...process.env };
    delete pipelineEnv.CLAUDECODE;

    const child = spawn("python", pythonArgs, {
      cwd: pipelineDir,
      stdio: "inherit",
      env: pipelineEnv,
    });
    forwardSignals(child);

    child.on("exit", (code) => process.exit(code ?? 0));
    child.on("error", (err) => {
      console.error(`Error launching pipeline: ${err.message}`);
      console.error("Make sure Python 3.11+ is installed.");
      process.exit(1);
    });
    return;
  }

  // ── Simple mode: launch tool with OpenRouter ──
  const model = resolveModel(args.model, models);
  const tool = model.tool || "claude";

  if (tool === "copilot") {
    const nodeMajor = getNodeMajorVersion();
    if (nodeMajor < 24) {
      console.error(
        `Error: Copilot CLI requires Node.js v24+.\n` +
          `Current Node version: v${process.versions.node}\n\n` +
          "Upgrade Node, then run: cloding -m copilot"
      );
      process.exit(1);
    }
  }

  // Validate API key (pipeline mode handles its own validation)
  const isPlanProvider = model.provider === "plan";
  const apiKeyEnv = model.api_key_env || "OPENROUTER_API_KEY";
  const apiKey = isPlanProvider ? "" : process.env[apiKeyEnv];
  const usingLinkedCliAuth = !apiKey && canUseCliLinkedAuth(tool);
  if (!apiKey && !usingLinkedCliAuth && !isPlanProvider) {
    console.error(
      `Error: ${apiKeyEnv} not set.\n\n` +
        `Please set it:  export ${apiKeyEnv}=...`
    );
    process.exit(1);
  }

  // Build env for tool
  const runEnv = { ...process.env };

  if (tool === "claude") {
    const provider = model.provider || "openrouter";
    if (provider === "plan") {
      // Paid plan: only set model, let Claude use its built-in auth
      runEnv.ANTHROPIC_MODEL = model.id;
    } else if (provider === "anthropic") {
      // Direct Anthropic API key
      runEnv.ANTHROPIC_API_KEY = apiKey;
      runEnv.ANTHROPIC_MODEL = model.id;
    } else {
      // OpenRouter (default)
      runEnv.ANTHROPIC_BASE_URL = OPENROUTER_BASE_URL;
      runEnv.ANTHROPIC_AUTH_TOKEN = apiKey;
      runEnv.ANTHROPIC_API_KEY = "";
      runEnv.ANTHROPIC_MODEL = model.id;
    }
    // Don't inherit CLAUDECODE — prevents "cannot launch inside another session" error
    delete runEnv.CLAUDECODE;
  } else if (tool === "gemini") {
    if (apiKey) {
      runEnv.GEMINI_API_KEY = apiKey;
    }
  } else if (tool === "opencode") {
    runEnv.OPENCODE_API_KEY = apiKey;
  } else if (tool === "codex") {
    if (apiKey) {
      runEnv.OPENAI_API_KEY = apiKey;
    }
  } else if (tool === "copilot") {
    if (apiKey) {
      runEnv.GITHUB_TOKEN = apiKey;
    }
  }

  // Build tool args
  const runArgs = [...args.claudeArgs];
  if (args.prompt) {
    if (tool === "claude" || tool === "gemini" || tool === "copilot") {
      runArgs.push("-p", args.prompt);
    } else if (tool === "opencode") {
      runArgs.unshift("run");
      runArgs.push(args.prompt);
    } else if (tool === "codex") {
      runArgs.push("exec", args.prompt);
    }
  }

  if (tool === "gemini") {
    if (model.id) {
      const modelId = usingLinkedCliAuth
        ? normalizeGeminiModelForLinkedAuth(model.id)
        : model.id;
      runArgs.push("--model", modelId);
    }
  } else if (tool === "opencode" && model.id) {
    runArgs.push("--model", model.id);
  } else if (tool === "codex") {
    if (model.id) runArgs.push("--model", model.id);
    if (args.prompt) runArgs.push("--full-auto");
    if (args.prompt && !hasArg(runArgs, "--skip-git-repo-check")) {
      runArgs.push("--skip-git-repo-check");
    }
  }

  // Print banner
  const costInfo =
    model.in > 0
      ? ` ($${model.in}/$${model.out} per Mtok)`
      : "";
  console.log(`\x1b[36m⚡ cloding\x1b[0m → ${model.name}${costInfo}`);

  if (model.in > 0 && model.out > 0 && models.opus) {
    const savings = Math.round(models.opus.out / model.out);
    if (savings > 1) {
      console.log(`\x1b[32m   ${savings}x cheaper than Opus\x1b[0m`);
    }
  }
  console.log("");

  if (isPlanProvider) {
    console.log(
      `\x1b[33mNote:\x1b[0m Using ${tool === "codex" ? "ChatGPT" : tool === "gemini" ? "Gemini" : "Claude"} paid plan/subscription. No API cost tracking.\n`
    );
  } else if (usingLinkedCliAuth) {
    console.log(
      `\x1b[33mNote:\x1b[0m ${apiKeyEnv} not set. Using existing ${tool} CLI account session.\n`
    );
  }

  // Launch tool
  // On Windows, npm globals are .cmd shims that need shell:true for resolution.
  const isWin = process.platform === "win32";
  // Map tool name to binary name (copilot tool uses `copilot` binary)
  let spawnTool = tool === "copilot" ? "copilot" : tool;
  let spawnArgs = runArgs;
  let spawnShell = isWin;

  if (tool === "codex" && isWin) {
    // Wrap with WSL
    spawnTool = "wsl";
    // Using --cd to current directory
    spawnArgs = ["--cd", process.cwd(), "codex", ...runArgs];
    spawnShell = false; // wsl is an .exe

    // Pass environment variables to WSL using WSLENV
    const wslenv = [];
    if (apiKeyEnv && apiKey) wslenv.push(`${apiKeyEnv}/u`);
    // Add common ones just in case (only if they exist)
    if (runEnv.OPENAI_API_KEY) wslenv.push("OPENAI_API_KEY/u");
    if (runEnv.OPENROUTER_API_KEY) wslenv.push("OPENROUTER_API_KEY/u");
    
    if (process.env.WSLENV) {
      runEnv.WSLENV = `${process.env.WSLENV}:${wslenv.join(":")}`;
    } else {
      runEnv.WSLENV = wslenv.join(":");
    }
  }

  // Suppress Node DEP0190 warning (shell:true + args on Windows)
  if (spawnShell) {
    const origEmit = process.emit.bind(process);
    process.emit = function (event, ...eArgs) {
      if (event === "warning" && eArgs[0]?.code === "DEP0190") return false;
      return origEmit(event, ...eArgs);
    };
  }

  const child = spawn(spawnTool, spawnArgs, {
    stdio: ["inherit", "inherit", "pipe"], // Inherit stdin/out, pipe stderr to filter noise
    env: runEnv,
    shell: spawnShell,
  });
  forwardSignals(child);

  // Filter WSL relay noise
  child.stderr.on("data", (data) => {
    const msg = data.toString();
    // Discard known non-fatal noise
    if (msg.includes("WSL (") && msg.includes("ERROR: CreateProcessParseCommon")) {
      return;
    }
    if (msg.includes("[DEP0190]") && msg.includes("DeprecationWarning")) {
      return;
    }
    process.stderr.write(data);
  });

  child.on("exit", (code) => process.exit(code ?? 0));
  child.on("error", (err) => {
    if (err.code === "ENOENT") {
      if (tool === "copilot") {
        console.error(
          "Error: 'copilot' command not found.\n\n" +
            "Install with: npm i -g @github/copilot\n" +
            "Then ensure your npm global bin is in PATH."
        );
      } else {
        console.error(
          `Error: '${tool}' command not found.\n\n` +
            `Install ${tool} first.`
        );
      }
    } else {
      console.error(`Error launching ${tool}: ${err.message}`);
    }
    process.exit(1);
  });
}

main();
