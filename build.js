#!/usr/bin/env bun

/**
 * build.js — Compile cloding into standalone binaries for all platforms.
 *
 * Usage:
 *   bun run build.js                         # Build all 5 targets
 *   bun run build.js --target=linux-x64      # Build one target
 *   bun run build.js --target=darwin          # Build all darwin targets
 *
 * Requires: Bun (https://bun.sh)
 * Output:   dist/cloding-{os}-{arch}[.exe]
 */

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"));
const version = pkg.version;

const TARGETS = [
  { target: "bun-linux-x64",    outfile: "dist/cloding-linux-x64" },
  { target: "bun-linux-arm64",  outfile: "dist/cloding-linux-arm64" },
  { target: "bun-darwin-x64",   outfile: "dist/cloding-darwin-x64" },
  { target: "bun-darwin-arm64", outfile: "dist/cloding-darwin-arm64" },
  { target: "bun-windows-x64",  outfile: "dist/cloding-win-x64.exe" },
];

function buildTarget(t) {
  console.log(`  Building ${t.outfile} (${t.target})...`);

  // Ensure output directory exists
  const dir = path.dirname(t.outfile);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  // Use bun build CLI for cross-compilation
  // All arguments are constants — no user input, safe to use spawnSync
  const args = [
    "build",
    "./bin/cloding.js",
    "--compile",
    `--target=${t.target}`,
    `--outfile=${t.outfile}`,
    "--minify",
  ];

  const result = spawnSync("bun", args, { stdio: "inherit" });

  if (result.status === 0) {
    try {
      const stat = fs.statSync(t.outfile);
      const sizeMB = (stat.size / 1024 / 1024).toFixed(1);
      console.log(`  ✓ ${t.outfile} (${sizeMB} MB)\n`);
    } catch {
      console.log(`  ✓ ${t.outfile}\n`);
    }
    return true;
  } else {
    console.error(`  ✗ Failed: ${t.outfile}\n`);
    return false;
  }
}

function main() {
  // Filter targets if --target specified
  const targetArg = process.argv.find((a) => a.startsWith("--target="));
  let targets = TARGETS;

  if (targetArg) {
    const filter = targetArg.split("=")[1];
    targets = TARGETS.filter(
      (t) => t.target.includes(filter) || t.outfile.includes(filter)
    );
    if (targets.length === 0) {
      console.error(`No targets matched: ${filter}`);
      console.error(`Available: ${TARGETS.map((t) => t.target).join(", ")}`);
      process.exit(1);
    }
  }

  console.log(`\n⚡ Building cloding v${version} for ${targets.length} target(s)\n`);

  let succeeded = 0;
  let failed = 0;

  for (const t of targets) {
    if (buildTarget(t)) {
      succeeded++;
    } else {
      failed++;
    }
  }

  console.log(`Done: ${succeeded} built, ${failed} failed.`);
  console.log(`Binaries in dist/\n`);
  if (failed > 0) process.exit(1);
}

main();
