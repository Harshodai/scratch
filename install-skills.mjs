#!/usr/bin/env node
/**
 * CentRAG Skills Installer v2
 * ============================
 * Clones skill repositories from GitHub and installs selected SKILL.md
 * files into .agents/skills/<skill-name>/SKILL.md
 *
 * Handles four real-world repo layouts discovered by research:
 *
 *   FLAT   — skills/<n>/SKILL.md
 *            (obra/superpowers, anthropics/skills, openclaw, charon-fan)
 *
 *   HIDDEN — .claude/skills/<n>/SKILL.md
 *            (pbakaus/impeccable — skills live in a pre-built Claude dist folder,
 *             NOT in a top-level "skills/" dir)
 *
 *   DEEP   — plugins/<plugin>/skills/<n>/SKILL.md
 *            (wshobson/agents — 149 skills nested two levels inside plugin dirs)
 *
 *   DOMAIN — <domain>/<n>/SKILL.md at repo root
 *            (alirezarezvani/claude-skills — engineering-team/, ai-ml-team/, etc.)
 *
 * Usage:
 *   node install-skills.mjs              install all configured skills
 *   node install-skills.mjs --dry-run    preview without writing anything
 *   node install-skills.mjs --update     re-install / overwrite existing skills
 *   node install-skills.mjs --list-repo owner/repo
 *                                        list every SKILL.md folder in a repo
 */

import { spawnSync } from "child_process";
import fs   from "fs";
import path from "path";
import os   from "os";

// ─── WHERE TO PUT THE SKILLS IN YOUR PROJECT ─────────────────────────────────

const SKILLS_TARGET_DIR = ".agents/skills";

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

// ─── SKILL SOURCE CONFIG ──────────────────────────────────────────────────────
//
//  layout       "flat"  → skills at skillsSubdir/<n>/SKILL.md
//               "deep"  → recursive search by folder name anywhere in repo
//
//  skillsSubdir only used for "flat"; the parent containing individual skill dirs
//
//  skills       exact folder names to install; ["*"] = install every skill found

const SKILL_SOURCES = [

  // ── Priority 1: obra/superpowers ─────────────────────────────────────────
  // Confirmed layout: skills/<n>/SKILL.md
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

  // ── Priority 2: pbakaus/impeccable ────────────────────────────────────────
  // The repo uses a BUILD SYSTEM. Source is in source/skills/ but that is NOT
  // the agent-ready format. The pre-built Claude Code output lives at:
  //   .claude/skills/<n>/SKILL.md
  // Confirmed by AGENTS.md in the repo:
  //   dist/claude-code/.claude/skills/*/SKILL.md
  // AND the .claude/skills/ folder is also committed at root for quick copy.
  {
    repo        : "https://github.com/pbakaus/impeccable.git",
    label       : "pbakaus/impeccable",
    layout      : "flat",
    skillsSubdir: ".claude/skills",
    skills      : ["audit", "harden", "optimize", "critique", "clarify", "normalize", "distill"],
  },

  // ── Priority 3: wshobson/agents ───────────────────────────────────────────
  // Confirmed layout: plugins/<plugin-name>/skills/<skill-name>/SKILL.md
  // There is no top-level "skills/" directory — everything is nested under plugins/.
  // "deep" layout does a recursive search by folder name.
  // Skill names confirmed from repo architecture docs:
  //   plugins/backend-development/skills/   → api-design-principles, architecture-patterns, microservices-patterns
  //   plugins/python-development/skills/    → python-performance-optimization, async-python-patterns
  //   plugins/developer-essentials/skills/  → code-review-excellence, debugging-strategies
  {
    repo  : "https://github.com/wshobson/agents.git",
    label : "wshobson/agents",
    layout: "deep",
    skills: [
      "api-design-principles",
      "python-performance-optimization",
      "architecture-patterns",
      "async-python-patterns",
      "microservices-patterns",
      "code-review-excellence",
      "debugging-strategies",
    ],
  },

  // ── Priority 4: anthropics/skills (Official Anthropic) ────────────────────
  // Confirmed layout: skills/<n>/SKILL.md
  {
    repo        : "https://github.com/anthropics/skills.git",
    label       : "anthropics/skills",
    layout      : "flat",
    skillsSubdir: "skills",
    skills      : ["skill-creator", "webapp-testing", "mcp-builder", "frontend-design"],
  },

  // ── Priority 5: useai-pro/openclaw-skills-security ────────────────────────
  {
    repo        : "https://github.com/useai-pro/openclaw-skills-security.git",
    label       : "useai-pro/openclaw-skills-security",
    layout      : "flat",
    skillsSubdir: "skills",
    skills      : ["skill-vetter"],
  },

  // ── Priority 6: charon-fan/agent-playbook ────────────────────────────────
  {
    repo        : "https://github.com/charon-fan/agent-playbook.git",
    label       : "charon-fan/agent-playbook",
    layout      : "flat",
    skillsSubdir: "skills",
    skills      : ["self-improving-agent"],
  },

  // ── Priority 7: alirezarezvani/claude-skills ─────────────────────────────
  // Confirmed layout: <domain-folder>/<skill-name>/SKILL.md at repo root
  //   engineering-team/senior-architect/SKILL.md
  //   ai-ml-team/ai-engineer/SKILL.md
  //   devops-team/senior-devops/SKILL.md
  //   etc.
  // The script resolved "root" before but found no matches because it was
  // looking for skills at the top level (engineering-team IS the top level, but
  // skills are one level deeper). "deep" layout handles this correctly.
  {
    repo  : "https://github.com/alirezarezvani/claude-skills.git",
    label : "alirezarezvani/claude-skills",
    layout: "deep",
    skills: [
      "senior-architect",
      "code-reviewer",
      "senior-security",
      "ai-engineer",
      "ml-pipeline-workflow",
      "senior-devops",
      "docker-expert",
      "database-admin",
      "postgresql-optimization",
      "test-automator",
      "tdd-orchestrator",
    ],
  },
];

// ─── UTILITIES ────────────────────────────────────────────────────────────────

const isDryRun = process.argv.includes("--dry-run");
const isUpdate = process.argv.includes("--update");

/** Recursively copy a directory tree */
function copyDirSync(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src,  entry.name);
    const d = path.join(dest, entry.name);
    entry.isDirectory() ? copyDirSync(s, d) : fs.copyFileSync(s, d);
  }
}

/** Verify git is on PATH */
function checkGit() {
  const r = spawnSync("git", ["--version"], { encoding: "utf8" });
  if (r.error || r.status !== 0) {
    console.error(`${RED}ERROR: git not found.${R} Install from https://git-scm.com/`);
    process.exit(1);
  }
}

/**
 * Shallow-clone repo into tmpBase.
 * Returns cloneDir (reuses it if already cloned this run).
 */
function cloneRepo(repoUrl, tmpBase) {
  const name     = repoUrl.replace(/\.git$/, "").split("/").at(-1);
  const cloneDir = path.join(tmpBase, name);
  if (fs.existsSync(cloneDir)) return cloneDir;  // already cloned this run

  info(`Cloning ${repoUrl} …`);
  const r = spawnSync(
    "git", ["clone", "--depth", "1", "--quiet", repoUrl, cloneDir],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  );
  if (r.status !== 0) throw new Error(r.stderr?.trim() || "git clone failed");
  return cloneDir;
}

/**
 * FLAT strategy: skill folder lives at skillsSubdir/<skillName>/
 * Returns the absolute path to the skill dir, or null.
 */
function findSkillFlat(cloneDir, skillsSubdir, skillName) {
  const candidate = path.join(cloneDir, skillsSubdir, skillName);
  return fs.existsSync(path.join(candidate, "SKILL.md")) ? candidate : null;
}

/**
 * DEEP strategy: walk the whole repo tree and return the first directory
 * whose basename === skillName and that contains SKILL.md.
 * Skips well-known non-skill directories for speed.
 */
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
        return full;   // exact match
      }

      const found = walk(full, depth + 1);
      if (found) return found;
    }
    return null;
  }

  return walk(repoRoot, 0);
}

/**
 * Collect all SKILL.md-containing directories anywhere in the repo.
 * Used by --list-repo and the "*" wildcard.
 */
function collectAllSkills(repoRoot) {
  const found = [];

  function walk(dir, depth) {
    if (depth > 6) return;
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); }
    catch (_) { return; }

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      if (DEEP_SKIP.has(entry.name)) continue;

      const full = path.join(dir, entry.name);
      if (fs.existsSync(path.join(full, "SKILL.md"))) {
        found.push({ name: entry.name, relativePath: path.relative(repoRoot, full) });
      }
      walk(full, depth + 1);
    }
  }

  walk(repoRoot, 0);
  return found;
}

// ─── MAIN ────────────────────────────────────────────────────────────────────

async function main() {
  head("CentRAG Skills Installer v2");
  rule();

  if (isDryRun) console.log(`${YELLOW}DRY RUN — no files will be written${R}`);
  if (isUpdate) console.log(`${CYAN}UPDATE MODE — overwrites existing skills${R}`);

  checkGit();

  const projectRoot = process.cwd();
  const targetDir   = path.join(projectRoot, SKILLS_TARGET_DIR);
  const tmpBase     = fs.mkdtempSync(path.join(os.tmpdir(), "centrag-skills-"));

  console.log(`\nProject root : ${projectRoot}`);
  console.log(`Skills target: ${targetDir}`);
  console.log(`Temp dir     : ${tmpBase}`);
  rule();

  if (!isDryRun) fs.mkdirSync(targetDir, { recursive: true });

  const results = { installed: [], skipped: [], notFound: [], errors: [] };

  for (const source of SKILL_SOURCES) {
    head(`📦  ${source.label}  [layout: ${source.layout}]`);

    // ── Clone ───────────────────────────────────────────────────────────────
    let cloneDir;
    try {
      cloneDir = cloneRepo(source.repo, tmpBase);
    } catch (err) {
      fail(`Clone failed: ${err.message}`);
      source.skills.forEach((s) => results.errors.push(`${source.label}/${s}`));
      continue;
    }

    // ── Validate flat root ──────────────────────────────────────────────────
    if (source.layout === "flat") {
      const skillsRoot = path.join(cloneDir, source.skillsSubdir);
      if (!fs.existsSync(skillsRoot)) {
        fail(`skillsSubdir "${source.skillsSubdir}" not found in this repo.`);
        dim(`Repo root contains: ${fs.readdirSync(cloneDir).slice(0, 10).join(", ")} …`);
        dim(`Run: node install-skills.mjs --list-repo ${source.label} to inspect`);
        source.skills.forEach((s) => results.notFound.push(`${source.label}/${s}`));
        continue;
      }
      dim(`Skills root → ${source.skillsSubdir}/`);
    } else {
      dim(`Recursive deep-search across repo tree`);
    }

    // ── Expand wildcard ─────────────────────────────────────────────────────
    let skillList = source.skills;
    if (skillList[0] === "*") {
      const all = source.layout === "flat"
        ? fs.readdirSync(path.join(cloneDir, source.skillsSubdir), { withFileTypes: true })
            .filter((e) => e.isDirectory() && fs.existsSync(
              path.join(cloneDir, source.skillsSubdir, e.name, "SKILL.md")))
            .map((e) => e.name)
        : collectAllSkills(cloneDir).map((s) => s.name);
      skillList = all;
    }

    // ── Install each skill ──────────────────────────────────────────────────
    for (const skillName of skillList) {
      const destSkillDir = path.join(targetDir, skillName);

      // Skip if already installed and not in --update mode
      if (fs.existsSync(destSkillDir) && !isUpdate) {
        info(`Already installed — skipping: ${skillName}`);
        results.skipped.push(skillName);
        continue;
      }

      // Find the skill source folder
      const srcSkillDir = source.layout === "flat"
        ? findSkillFlat(cloneDir, source.skillsSubdir, skillName)
        : findSkillDeep(cloneDir, skillName);

      if (!srcSkillDir) {
        warn(`Not found in repo: ${skillName}`);
        dim(`Tip: run --list-repo ${source.label} to see all available skills`);
        results.notFound.push(`${source.label}/${skillName}`);
        continue;
      }

      if (isDryRun) {
        ok(`[DRY RUN] Would install: ${skillName}  ← ${path.relative(cloneDir, srcSkillDir)}`);
        results.installed.push(skillName);
        continue;
      }

      // Copy the skill folder (SKILL.md + all supporting files)
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

  // ── Cleanup temp dir ────────────────────────────────────────────────────────
  try { fs.rmSync(tmpBase, { recursive: true, force: true }); } catch (_) {}

  // ── Final summary ───────────────────────────────────────────────────────────
  head("Summary");
  rule();
  console.log(`${GREEN}Installed : ${results.installed.length}${R}`);
  console.log(`${DIM}Skipped   : ${results.skipped.length}${R}`);
  console.log(`${YELLOW}Not found : ${results.notFound.length}${R}`);
  console.log(`${RED}Errors    : ${results.errors.length}${R}`);

  if (results.installed.length) {
    console.log(`\n${GREEN}Installed skills:${R}`);
    results.installed.forEach((s) => console.log(`  • ${s}`));
  }
  if (results.skipped.length) {
    console.log(`\n${DIM}Skipped (already installed — use --update to overwrite):${R}`);
    results.skipped.forEach((s) => console.log(`  • ${s}`));
  }
  if (results.notFound.length) {
    console.log(`\n${YELLOW}Not found (skill folder name may have changed in the repo):${R}`);
    results.notFound.forEach((s) => console.log(`  • ${s}`));
    console.log(`\n  To inspect a repo: node install-skills.mjs --list-repo owner/repo`);
  }
  if (results.errors.length) {
    console.log(`\n${RED}Errors:${R}`);
    results.errors.forEach((s) => console.log(`  • ${s}`));
  }

  rule();
  if (!isDryRun && results.installed.length > 0) {
    console.log(`\n${GREEN}${BOLD}Done!${R} Skills installed to: ${targetDir}`);
    console.log(`\nVerify:  ls ${SKILLS_TARGET_DIR}/`);
  }

  if (results.errors.length > 0 || results.notFound.length > 0) process.exit(1);
}

// ─── --list-repo  (bonus utility) ────────────────────────────────────────────
//
//  Lists every SKILL.md-containing directory in any repo.
//  Use this whenever a skill shows "Not found" to discover the real folder name.
//
//  node install-skills.mjs --list-repo pbakaus/impeccable
//  node install-skills.mjs --list-repo wshobson/agents
//  node install-skills.mjs --list-repo alirezarezvani/claude-skills

if (process.argv.includes("--list-repo")) {
  const idx     = process.argv.indexOf("--list-repo");
  const repoArg = process.argv[idx + 1];

  if (!repoArg || repoArg.startsWith("--")) {
    console.error("Usage: node install-skills.mjs --list-repo owner/repo");
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

  const skills = collectAllSkills(cloneDir);
  console.log(`\nFound ${skills.length} skills in ${repoArg}:\n`);
  skills.forEach(({ name: n, relativePath: rp }) =>
    console.log(`  ${GREEN}${n.padEnd(40)}${R}  ${DIM}← ${rp}${R}`)
  );

  try { fs.rmSync(tmpBase, { recursive: true, force: true }); } catch (_) {}
  process.exit(0);
}

main().catch((err) => {
  console.error(`\n${RED}Fatal error:${R}`, err.message);
  process.exit(1);
});
