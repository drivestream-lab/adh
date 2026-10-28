const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const root = path.join(__dirname, "..");
const release = path.join(root, "release");
const archDir = process.arch === "arm64" ? "mac-arm64" : "mac";
const candidates = [
  path.join(release, archDir, "Buzz.app"),
  path.join(release, "mac", "Buzz.app"),
  path.join(release, "mac-arm64", "Buzz.app"),
];
const src = candidates.find((p) => fs.existsSync(p));
if (!src) {
  console.error("Buzz.app not found under", release);
  process.exit(1);
}
const dest = "/Applications/Buzz.app";
if (fs.existsSync(dest)) {
  fs.rmSync(dest, { recursive: true, force: true });
}
execFileSync("cp", ["-R", src, dest]);
console.log("Installed", dest);
execFileSync("open", ["-a", "Buzz"]);
