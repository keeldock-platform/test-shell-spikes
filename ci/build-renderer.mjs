import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = join(root, "apps/desktop/dist/web");
const renderer = join(root, "apps/desktop/web");
const api = join(root, "node_modules/@tauri-apps/api");

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await cp(renderer, output, { recursive: true });
await mkdir(join(output, "vendor/@tauri-apps"), { recursive: true });
await cp(api, join(output, "vendor/@tauri-apps/api"), { recursive: true });
await cp(join(root, "pages/colour"), join(output, "pages/colour"), { recursive: true, force: true });
console.log(`renderer assembled at ${output}`);
