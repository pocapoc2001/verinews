import { defineConfig, globalIgnores } from "eslint/config";
import next from "eslint-config-next";

export default defineConfig([
  globalIgnores([
    ".venv/**", ".next/**", "node_modules/**", "public/**",
    "RoEduNet_proiect/**", "build_check/**", "runs/**", "model_state/**",
  ]),
  { extends: [...next] },
]);
