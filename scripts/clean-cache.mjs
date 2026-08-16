import { readdir, rm, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const argumentsSet = new Set(process.argv.slice(2).filter((argument) => argument !== "--"));
const dryRun = argumentsSet.has("--dry-run");
const includeLegacyVenv = argumentsSet.has("--include-legacy-venv");
const supportedArguments = new Set(["--dry-run", "--include-legacy-venv"]);
const unknownArguments = [...argumentsSet].filter((argument) => !supportedArguments.has(argument));

if (unknownArguments.length > 0) {
  throw new Error(`Unknown arguments: ${unknownArguments.join(", ")}`);
}

const cacheDirectoryNames = new Set([
  "__pycache__",
  ".pytest_cache",
  ".ruff_cache",
  ".mypy_cache",
  ".pyright",
  ".langgraph_api",
  "htmlcov",
]);
const prunedDirectoryNames = new Set([".git", ".venv", "node_modules"]);
const legacyVenv = path.join(repositoryRoot, "services", "agent", ".venv");
const targets = new Set();

await collectTargets(repositoryRoot);
if (includeLegacyVenv && (await exists(legacyVenv))) {
  targets.add(legacyVenv);
}

const orderedTargets = [...targets].sort((left, right) => right.length - left.length);
for (const target of orderedTargets) {
  assertInsideRepository(target);
  console.log(`${dryRun ? "would remove" : "removed"} ${path.relative(repositoryRoot, target)}`);
  if (!dryRun) {
    await rm(target, { force: true, maxRetries: 3, recursive: true });
  }
}

console.log(`${dryRun ? "found" : "removed"} ${orderedTargets.length} cache target(s)`);

async function collectTargets(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const absolutePath = path.join(directory, entry.name);

    if (entry.isSymbolicLink()) {
      continue;
    }
    if (entry.isDirectory() && cacheDirectoryNames.has(entry.name)) {
      targets.add(absolutePath);
      continue;
    }
    if (entry.isDirectory() && entry.name === "node_modules") {
      const viteCache = path.join(absolutePath, ".vite");
      if (await exists(viteCache)) {
        targets.add(viteCache);
      }
      continue;
    }
    if (entry.isDirectory() && prunedDirectoryNames.has(entry.name)) {
      continue;
    }
    if (entry.isDirectory()) {
      await collectTargets(absolutePath);
      continue;
    }
    if (entry.isFile() && isCacheFile(entry.name)) {
      targets.add(absolutePath);
    }
  }
}

function isCacheFile(name) {
  return name.endsWith(".pyc") || name.endsWith(".pyo") || name.endsWith(".tsbuildinfo") || name === ".coverage";
}

function assertInsideRepository(target) {
  const relativePath = path.relative(repositoryRoot, path.resolve(target));
  if (!relativePath || relativePath.startsWith(`..${path.sep}`) || path.isAbsolute(relativePath)) {
    throw new Error(`Refusing to remove a target outside the repository: ${target}`);
  }
}

async function exists(target) {
  try {
    await stat(target);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") {
      return false;
    }
    throw error;
  }
}
