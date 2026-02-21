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
  // Search for .env in: cwd, then cloding package root
  const candidates = [
    path.join(process.cwd(), ".env"),
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
  const modelsPath = path.join(__dirname, "..", "models.json");
  let models;
  try {
    models = JSON.parse(fs.readFileSync(modelsPath, "utf8"));
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
    if (!m.id || typeof m.id !== "string") {
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
  cloding pipeline "Add auth"        Run the full pipeline (requires Python)
  cloding docker <command>           Docker container management

OPTIONS:
  -m, --model <name|id>   Model shortcut or full OpenRouter model ID
  -p, --prompt <text>     Run non-interactively with a single prompt
      --list-models       Show available models with pricing
  -v, --version           Show version
  -h, --help              Show this help

DOCKER COMMANDS:
  cloding docker build               Build the cloding Docker image
  cloding docker run "prompt"         Run a prompt in a container
  cloding docker shell                Interactive claude session in a container
  cloding docker status               Show running cloding containers
  cloding docker stop                 Stop all cloding containers
  cloding docker clean                Remove stopped cloding containers
  cloding docker help                 Show Docker help

MODELS (shortcuts):
  qwen       Qwen 3 Coder        $0.07/$0.30 per Mtok  (default, ~71x cheaper)
  haiku      Claude Haiku 4.5     $0.80/$4.00 per Mtok
  sonnet     Claude Sonnet 4      $3.00/$15.00 per Mtok
  opus       Claude Opus 4.6      $15.00/$75.00 per Mtok
  deepseek   DeepSeek Coder V3    $0.14/$0.28 per Mtok
  gemini     Gemini 2.5 Pro       $1.25/$10.00 per Mtok

  Or pass any OpenRouter model ID:
    cloding -m meta-llama/llama-4-scout

ENVIRONMENT:
  OPENROUTER_API_KEY       Required. Your OpenRouter API key.
  CLODING_DEFAULT_MODEL    Optional. Default model shortcut (default: qwen).

EXAMPLES:
  cloding                            # Start coding with Qwen ($0.07/Mtok)
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

function dockerAvailable() {
  try {
    const result = spawnSync("docker", ["--version"], { stdio: "ignore" });
    return result.status === 0;
  } catch {
    return false;
  }
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
        // First unrecognized non-flag arg is the prompt (for 'run' mode)
        if (!interactive && !prompt && !arg.startsWith("-")) {
          prompt = arg;
        } else {
          extraClaudeArgs.push(arg);
        }
        break;
    }
    i++;
  }

  // Validate
  if (!interactive && !prompt) {
    console.error(
      'Error: No prompt provided.\n\n' +
        '  Usage: cloding docker run "your prompt here"\n'
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

  const apiKey = process.env.OPENROUTER_API_KEY;
  if (!apiKey) {
    console.error(
      "Error: OPENROUTER_API_KEY not set.\n\n" +
        "Get your key at https://openrouter.ai/keys\n" +
        "Then: export OPENROUTER_API_KEY=sk-or-v1-...\n"
    );
    process.exit(1);
  }

  // Resolve model
  const model = resolveModel(modelArg, models);
  const tool = model.tool || "claude";

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

  // Write env vars to a temp file so the API key doesn't leak in `ps aux`
  const envVars = [
    `ANTHROPIC_BASE_URL=${OPENROUTER_BASE_URL}`,
    `ANTHROPIC_AUTH_TOKEN=${apiKey}`,
    `ANTHROPIC_API_KEY=`,
    `ANTHROPIC_MODEL=${model.id}`,
    `CLAUDECODE=`,
    `GEMINI_API_KEY=${apiKey}`,
    `OPENCODE_API_KEY=${apiKey}`,
    `OPENAI_API_KEY=${apiKey}`,
  ];
  const envFileContent = envVars.join("\n") + "\n";
  const envFilePath = path.join(os.tmpdir(), `cloding-env-${Date.now()}.tmp`);
  fs.writeFileSync(envFilePath, envFileContent, { mode: 0o600 });

  // Build docker command — uses spawn with argument array (safe, no shell injection)
  const cmd = ["docker", "run"];

  if (interactive) {
    cmd.push("-it");
  }

  if (autoRemove) {
    cmd.push("--rm");
  }

  cmd.push(
    "--name", containerName,
    "--network", DOCKER_NETWORK,
    "--memory", memory,
    "--cpus", cpus,
    "-v", `${workspace}:/workspace`,
    "--env-file", envFilePath
  );

  if (tool !== "claude") {
    cmd.push("--entrypoint", tool);
  }

  cmd.push(DOCKER_IMAGE);

  // Add tool-specific args
  if (!interactive && prompt) {
    if (tool === "claude" || tool === "gemini") {
      cmd.push("-p", prompt);
    } else if (tool === "opencode") {
      cmd.push("run", prompt);
    } else if (tool === "codex") {
      cmd.push(prompt);
    }
  }

  if (tool === "gemini") {
    cmd.push("--non-interactive");
    if (model.id) cmd.push("--model", model.id);
  } else if (tool === "opencode" && model.id) {
    cmd.push("--model", model.id);
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
  console.log("");

  // Clean up env file on exit (contains API key)
  function cleanupEnvFile() {
    try { fs.unlinkSync(envFilePath); } catch {}
  }

  // Spawn docker — uses argument array (no shell interpretation)
  const child = spawn(cmd[0], cmd.slice(1), {
    stdio: "inherit",
  });
  forwardSignals(child);

  child.on("exit", (code) => {
    cleanupEnvFile();
    process.exit(code ?? 0);
  });
  child.on("error", (err) => {
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

  // Validate API key (pipeline mode handles its own validation)
  const apiKeyEnv = model.api_key_env || "OPENROUTER_API_KEY";
  const apiKey = process.env[apiKeyEnv];
  if (!apiKey) {
    console.error(
      `Error: ${apiKeyEnv} not set.\n\n` +
        `Please set it:  export ${apiKeyEnv}=...`
    );
    process.exit(1);
  }

  // Build env for tool
  const runEnv = { ...process.env };
  
  if (tool === "claude") {
    runEnv.ANTHROPIC_BASE_URL = OPENROUTER_BASE_URL;
    runEnv.ANTHROPIC_AUTH_TOKEN = apiKey;
    runEnv.ANTHROPIC_API_KEY = "";
    runEnv.ANTHROPIC_MODEL = model.id;
    // Don't inherit CLAUDECODE — prevents "cannot launch inside another session" error
    delete runEnv.CLAUDECODE;
  } else if (tool === "gemini") {
    runEnv.GEMINI_API_KEY = apiKey;
  } else if (tool === "opencode") {
    runEnv.OPENCODE_API_KEY = apiKey;
  } else if (tool === "codex") {
    runEnv.OPENAI_API_KEY = apiKey;
  }

  // Build tool args
  const runArgs = [...args.claudeArgs];
  if (args.prompt) {
    if (tool === "claude" || tool === "gemini") {
      runArgs.push("-p", args.prompt);
    } else if (tool === "opencode") {
      runArgs.unshift("run");
      runArgs.push(args.prompt);
    } else if (tool === "codex") {
      runArgs.push(args.prompt);
    }
  }

  if (tool === "gemini") {
    runArgs.push("--non-interactive");
    if (model.id) runArgs.push("--model", model.id);
  } else if (tool === "opencode" && model.id) {
    runArgs.push("--model", model.id);
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

  // Launch tool
  // On Windows, npm globals are .cmd shims that need shell:true for resolution.
  const isWin = process.platform === "win32";
  let spawnTool = tool;
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
    if (apiKeyEnv) wslenv.push(`${apiKeyEnv}/u`);
    // Add common ones just in case
    wslenv.push("OPENAI_API_KEY/u");
    wslenv.push("OPENROUTER_API_KEY/u");
    
    if (process.env.WSLENV) {
      runEnv.WSLENV = `${process.env.WSLENV}:${wslenv.join(":")}`;
    } else {
      runEnv.WSLENV = wslenv.join(":");
    }
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
    // Discard the known non-fatal WSL relay error
    if (msg.includes("WSL (") && msg.includes("ERROR: CreateProcessParseCommon")) {
      return;
    }
    process.stderr.write(data);
  });

  child.on("exit", (code) => process.exit(code ?? 0));
  child.on("error", (err) => {
    if (err.code === "ENOENT") {
      console.error(
        `Error: '${tool}' command not found.\n\n` +
          `Install ${tool} first.`
      );
    } else {
      console.error(`Error launching ${tool}: ${err.message}`);
    }
    process.exit(1);
  });
}

main();
