import fs from "node:fs";
import path from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const schema = JSON.parse(fs.readFileSync(path.join(root, "cases/schema.json"), "utf8"));
const ajv = new Ajv2020({ allErrors: true, strict: false });
const validate = ajv.compile(schema);
const caseFiles = ["s01", "s02", "s03", "s08", "s10", "s11"];
const failures = [];

for (const spike of caseFiles) {
  const file = path.join(root, "cases", `${spike}.json`);
  const value = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!validate(value)) {
    failures.push(`${path.relative(root, file)}: ${ajv.errorsText(validate.errors, { separator: "; " })}`);
  }
}

if (failures.length) {
  process.stderr.write(`Draft 2020-12 case validation failed:\n${failures.map((item) => `- ${item}`).join("\n")}\n`);
  process.exitCode = 1;
} else {
  process.stdout.write("All lane case files satisfy the Draft 2020-12 schema.\n");
}
