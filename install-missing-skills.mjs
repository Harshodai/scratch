#!/usr/bin/env node
/**
 * CentRAG — Missing Skills Remediation
 * ======================================
 * Installs ONLY the skills that failed in the previous run:
 *
 *   1. obra/superpowers (11 skills) — failed due to transient network reset.
 *      Fixed with: 3 retry attempts, 5-second delay between each.
 *
 *   2. alirezarezvani/claude-skills (3 real skills missed):
 *      The plan doc used assumed names that don't exist in the repo.
 *      Verified real folder names from INSTALLATION.md + openclaw archive:
 *        ai-engineer       → senior-ml-engineer
 *        database-admin    → senior-data-engineer  (confirmed SKILL.md exists)
 *        test-automator    → senior-qa             (confirmed in INSTALLATION.md)
 *
 *      The following 4 are NOT real skills in this repo and are skipped:
 *        ml-pipeline-workflow   (no separate skill; covered by senior-ml-engineer)
 *        docker-expert          (no separate skill; senior-devops already installed)
 *        postgresql-optimization (no separate skill; covered by senior-data-engineer)
 *        tdd-orchestrator       (is an AGENT file in wshobson/agents, not a SKILL)
 *
 * Usage:
 *   node install-missing-skills.mjs            install missing skills
 *   node install-missing-skills.mjs --dry-run  preview only
 *   node install-missing-skills.mjs --update   overwrite if already exists
 */

import { spawnSync } from "child_process";
import fs   from "fs";
import path from "path";
import os   from "os";

// ─── CONFIG ──────────────────────────────────────────────────────────────────

const SKILLS_TARGET_DIR = ".agents/skills";
const CLONE_RETRIES     = 3;
const RETRY_DELAY_MS    = 5000;

const MISSING_SOURCES = [
  // ── 1. obra/superpowers ─────────────────────────────────────────────────
  // Transient network failure; retry logic added. Layout confirmed correct.
  {
    repo        : "https://github.com/obra/superpowers.git",
    label       : "obra/superpowers",
    layout      : "flat",
    skillsSubdir: "skills",
    skills: [
      "verification-before-completion",
      "test-driven-development",
      "systematic-debugging",
      "writing-plans",
      "executing-plans",
      "requesting-code-review",
      "receiving-code-review",
      "subagent-driven-development",
      "dispatching-parallel-agents",
      "finishing-a-development-branch",
      "writing-skills",
    ],
  },

  // ── 2. alirezarezvani/claude-skills ─────────────────────────────────────
  // Skills installed in previous run came from .gemini/skills/ inside the repo.
  // New skills to add use "deep" layout to find them wherever they live.
  // Verified names:
  //   senior-ml-engineer  → ai-engineer equivalent (openclaw archive)
  //   senior-data-engineer → database-admin equivalent (confirmed SKILL.md)
  //   senior-qa           → test-automator equivalent (INSTALLATION.md)
  {
    repo  : "https://github.com/alirezarezvani/claude-skills.git",
    label : "alirezarezvani/claude-skills",
    layout: "deep",
    skills: [
      "senior-ml-engineer",
      "senior-data-engineer",
      "senior-qa",
    ],
  },
];

// ─── COLOUR HELPERS ──────────────────────────────────────────────────────────

const R    = "\x1b[0m";
const BOLD = "\x1b[1m";
const GREEN  = "\x1b[32m";
const YELLOW = "\x1b[33m";
const RED    = "\x1b[31m";
const CYAN   = "\x1b[36m";
const DIM    = "\x1b[2m";

const ok   = (m) => console.log(`  ${GREEN}✓${R}  ${m}`);
const warn = (m) => console.log(`  ${YELLOW}⚠${R}  ${m}`);
const fail = (m) => console.log(`  ${RED}✗${R}  ${m}`);
const info = (m) => console.log(`  ${CYAN}→${R}  ${m}`);
const dim  = (m) => console.log(`     ${DIM}${m}${R}`);
const head = (m) => console.log(`\n${BOLD}${m}${R}`);
const rule = ()  => console.log("─".repeat(62));

// ─── UTILITIES ────────────────────────────────────────────────────────────────

const isDryRun = process.argv.includes("--dry-run");
const isUpdate = process.argv.includes("--update");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function copyDirSync(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src,  entry.name);
    const d = path.join(dest, entry.name);
    entry.isDirectory() ? copyDirSync(s, d) : fs.copyFileSync(s, d);
  }
}

function checkGit() {
  const r = spawnSync("git", ["--version"], { encoding: "utf8" });
  if (r.error || r.status !== 0) {
    console.error(`${RED}ERROR: git not found.${R}`);
    process.exit(1);
  }
}

/**
 * Clone repo with retry logic.
 * Returns cloneDir on success, throws after all retries exhausted.
 */
async function cloneWithRetry(repoUrl, tmpBase) {
  const name     = repoUrl.replace(/\.git$/, "").split("/").at(-1);
  const cloneDir = path.join(tmpBase, name);

  // Already cloned in this run — reuse
  if (fs.existsSync(cloneDir)) return cloneDir;

  for (let attempt = 1; attempt <= CLONE_RETRIES; attempt++) {
    info(`Cloning ${repoUrl} (attempt ${attempt}/${CLONE_RETRIES}) …`);

    const r = spawnSync(
      "git", ["clone", "--depth", "1", "--quiet", repoUrl, cloneDir],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
    );

    if (r.status === 0) return cloneDir;

    const errMsg = r.stderr?.trim() || "git clone failed";
    fail(`Attempt ${attempt} failed: ${errMsg}`);

    // Clean up partial clone so next attempt starts fresh
    if (fs.existsSync(cloneDir)) {
      fs.rmSync(cloneDir, { recursive: true, force: true });
    }

    if (attempt < CLONE_RETRIES) {
      info(`Waiting ${RETRY_DELAY_MS / 1000}s before retry …`);
      await sleep(RETRY_DELAY_MS);
    }
  }

  throw new Error(`All ${CLONE_RETRIES} clone attempts failed for ${repoUrl}`);
}

// ─── SKILL FINDERS ────────────────────────────────────────────────────────────

function findSkillFlat(cloneDir, skillsSubdir, skillName) {
  const candidate = path.join(cloneDir, skillsSubdir, skillName);
  return fs.existsSync(path.join(candidate, "SKILL.md")) ? candidate : null;
}

const DEEP_SKIP = new Set([
  ".git", "node_modules", ".github", "dist", "scripts", "docs",
  "api", "public", "source", "src", "test", "tests", "examples",
  "assets", "references", "commands", "agents", "hooks",
]);

function findSkillDeep(repoRoot, skillName) {
  function walk(dir, depth) {
    if (depth > 6) return null;
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); }
    catch (_) { return null; }

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      if (DEEP_SKIP.has(entry.name)) continue;
      const full = path.join(dir, entry.name);
      if (entry.name === skillName && fs.existsSync(path.join(full, "SKILL.md"))) {
        return full;
      }
      const found = walk(full, depth + 1);
      if (found) return found;
    }
    return null;
  }
  return walk(repoRoot, 0);
}

// ─── MAIN ────────────────────────────────────────────────────────────────────

async function main() {
  head("CentRAG — Missing Skills Remediation");
  rule();

  if (isDryRun) console.log(`${YELLOW}DRY RUN — no files will be written${R}`);
  if (isUpdate) console.log(`${CYAN}UPDATE MODE — overwrites existing skills${R}`);

  checkGit();

  const projectRoot = process.cwd();
  const targetDir   = path.join(projectRoot, SKILLS_TARGET_DIR);
  const tmpBase     = fs.mkdtempSync(path.join(os.tmpdir(), "centrag-missing-"));

  console.log(`\nProject root : ${projectRoot}`);
  console.log(`Skills target: ${targetDir}`);
  rule();

  if (!isDryRun) fs.mkdirSync(targetDir, { recursive: true });

  const results = { installed: [], skipped: [], notFound: [], errors: [] };

  for (const source of MISSING_SOURCES) {
    head(`📦  ${source.label}  [${source.layout}]`);

    // ── Clone (with retry) ──────────────────────────────────────────────────
    let cloneDir;
    try {
      cloneDir = await cloneWithRetry(source.repo, tmpBase);
      ok(`Cloned successfully`);
    } catch (err) {
      fail(`All clone attempts failed: ${err.message}`);
      fail(`Check your network / VPN / proxy settings and re-run.`);
      source.skills.forEach((s) => results.errors.push(`${source.label}/${s}`));
      continue;
    }

    // ── Validate flat root ──────────────────────────────────────────────────
    if (source.layout === "flat") {
      const skillsRoot = path.join(cloneDir, source.skillsSubdir);
      if (!fs.existsSync(skillsRoot)) {
        fail(`skillsSubdir "${source.skillsSubdir}" not found in repo.`);
        dim(`Repo root: ${fs.readdirSync(cloneDir).slice(0, 12).join(", ")}`);
        source.skills.forEach((s) => results.notFound.push(`${source.label}/${s}`));
        continue;
      }
      dim(`Skills root → ${source.skillsSubdir}/`);
    } else {
      dim(`Deep-search across full repo tree`);
    }

    // ── Install each skill ──────────────────────────────────────────────────
    for (const skillName of source.skills) {
      const destSkillDir = path.join(targetDir, skillName);

      if (fs.existsSync(destSkillDir) && !isUpdate) {
        info(`Already installed — skipping: ${skillName}`);
        results.skipped.push(skillName);
        continue;
      }

      const srcSkillDir = source.layout === "flat"
        ? findSkillFlat(cloneDir, source.skillsSubdir, skillName)
        : findSkillDeep(cloneDir, skillName);

      if (!srcSkillDir) {
        warn(`Not found in repo: ${skillName}`);
        dim(`Run: node install-missing-skills.mjs --list-repo ${source.label}`);
        results.notFound.push(`${source.label}/${skillName}`);
        continue;
      }

      if (isDryRun) {
        ok(`[DRY RUN] ${skillName}  ← ${path.relative(cloneDir, srcSkillDir)}`);
        results.installed.push(skillName);
        continue;
      }

      try {
        if (fs.existsSync(destSkillDir)) fs.rmSync(destSkillDir, { recursive: true, force: true });
        copyDirSync(srcSkillDir, destSkillDir);
        ok(`Installed: ${skillName}  ← ${path.relative(cloneDir, srcSkillDir)}`);
        results.installed.push(skillName);
      } catch (err) {
        fail(`Copy failed: ${skillName} — ${err.message}`);
        results.errors.push(`${source.label}/${skillName}`);
      }
    }
  }

  // ── Cleanup ─────────────────────────────────────────────────────────────────
  try { fs.rmSync(tmpBase, { recursive: true, force: true }); } catch (_) {}

  // ── Summary ──────────────────────────────────────────────────────────────────
  head("Summary");
  rule();
  console.log(`${GREEN}Installed : ${results.installed.length}${R}`);
  console.log(`${DIM}Skipped   : ${results.skipped.length}${R}`);
  console.log(`${YELLOW}Not found : ${results.notFound.length}${R}`);
  console.log(`${RED}Errors    : ${results.errors.length}${R}`);

  if (results.installed.length) {
    console.log(`\n${GREEN}Installed:${R}`);
    results.installed.forEach((s) => console.log(`  • ${s}`));
  }
  if (results.skipped.length) {
    console.log(`\n${DIM}Skipped (use --update to overwrite):${R}`);
    results.skipped.forEach((s) => console.log(`  • ${s}`));
  }
  if (results.notFound.length) {
    console.log(`\n${YELLOW}Still not found:${R}`);
    results.notFound.forEach((s) => console.log(`  • ${s}`));
    console.log(`\n  Inspect with: node install-missing-skills.mjs --list-repo owner/repo`);
  }
  if (results.errors.length) {
    console.log(`\n${RED}Errors (likely network — re-run the script):${R}`);
    results.errors.forEach((s) => console.log(`  • ${s}`));
  }

  rule();

  if (results.installed.length > 0 && !isDryRun) {
    console.log(`\n${GREEN}${BOLD}Done!${R} Run: ls ${SKILLS_TARGET_DIR}/  to verify.`);
  }

  if (results.errors.length > 0 || results.notFound.length > 0) process.exit(1);
}

// ─── --list-repo utility ─────────────────────────────────────────────────────
// Lists every folder with a SKILL.md anywhere in a repo.
// Use when a skill shows "Not found" to discover the real folder name.
//
//   node install-missing-skills.mjs --list-repo alirezarezvani/claude-skills

if (process.argv.includes("--list-repo")) {
  const idx     = process.argv.indexOf("--list-repo");
  const repoArg = process.argv[idx + 1];
  if (!repoArg || repoArg.startsWith("--")) {
    console.error("Usage: node install-missing-skills.mjs --list-repo owner/repo");
    process.exit(1);
  }

  checkGit();

  const tmpBase  = fs.mkdtempSync(path.join(os.tmpdir(), "centrag-list-"));
  const repoUrl  = `https://github.com/${repoArg}.git`;
  const name     = repoArg.split("/").at(-1);
  const cloneDir = path.join(tmpBase, name);

  console.log(`\nCloning ${repoUrl} …`);
  const r = spawnSync(
    "git", ["clone", "--depth", "1", "--quiet", repoUrl, cloneDir],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  );
  if (r.status !== 0) { console.error(r.stderr); process.exit(1); }

  const found = [];
  function walkList(dir, depth) {
    if (depth > 6) return;
    try {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        if (!e.isDirectory() || DEEP_SKIP.has(e.name)) continue;
        const full = path.join(dir, e.name);
        if (fs.existsSync(path.join(full, "SKILL.md"))) {
          found.push({ name: e.name, rel: path.relative(cloneDir, full) });
        }
        walkList(full, depth + 1);
      }
    } catch (_) {}
  }
  walkList(cloneDir, 0);

  console.log(`\nFound ${found.length} skills in ${repoArg}:\n`);
  found.forEach(({ name: n, rel }) =>
    console.log(`  ${GREEN}${n.padEnd(36)}${R}  ${DIM}← ${rel}${R}`)
  );

  try { fs.rmSync(tmpBase, { recursive: true, force: true }); } catch (_) {}
  process.exit(0);
}

main().catch((err) => {
  console.error(`\n${RED}Fatal error:${R}`, err.message);
  process.exit(1);
});
