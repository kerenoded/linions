import { copyFileSync, cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(process.cwd());
const buildDir = resolve(root, "dist");
const publicDir = resolve(root, "public");
const publicOutDir = resolve(root, "dist-public");
const studioOutDir = resolve(root, "dist-studio");

const PUBLIC_JS_FILES = [
  "config.js",
  "episode-loader.js",
  "gallery.js",
  "github.js",
  "player.js",
  "routes.js",
  "state-machine.js",
  "viewer.js",
];

const PUBLIC_STATIC_FILES = [
  "app.css",
  "player-frame.css",
  "favicon.svg",
  "index.html",
];

function resetDir(path) {
  rmSync(path, { recursive: true, force: true });
  mkdirSync(path, { recursive: true });
}

function copySharedPublicAssets(targetDir, excludedFiles) {
  cpSync(publicDir, targetDir, {
    recursive: true,
    filter: (source) => {
      const basename = source.split("/").pop() ?? source.split("\\").pop() ?? source;
      return !excludedFiles.has(basename);
    },
  });
}

function copyJsFile(targetDir, fileName) {
  const sourcePath = resolve(buildDir, fileName);
  if (!existsSync(sourcePath)) {
    throw new Error(`Missing compiled frontend module: ${fileName}`);
  }
  copyFileSync(sourcePath, resolve(targetDir, fileName));
}

function copyStaticFile(targetDir, fileName) {
  const sourcePath = resolve(publicDir, fileName);
  if (!existsSync(sourcePath)) {
    throw new Error(`Missing public asset: ${fileName}`);
  }
  copyFileSync(sourcePath, resolve(targetDir, fileName));
}

resetDir(publicOutDir);
resetDir(studioOutDir);

cpSync(buildDir, studioOutDir, { recursive: true });
copySharedPublicAssets(studioOutDir, new Set(["index.html", "studio.html"]));
copyFileSync(resolve(publicDir, "studio.html"), resolve(studioOutDir, "index.html"));

for (const fileName of PUBLIC_JS_FILES) {
  copyJsFile(publicOutDir, fileName);
}
for (const fileName of PUBLIC_STATIC_FILES) {
  copyStaticFile(publicOutDir, fileName);
}
