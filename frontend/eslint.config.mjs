import { defineConfig } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
export default defineConfig([{
    extends: [...nextCoreWebVitals],
    rules: {
        // Next 16 enables React Compiler diagnostics in its recommended config.
        // This application does not enable the compiler yet; keep the existing
        // hooks lint contract until compiler adoption is handled separately.
        "react-hooks/error-boundaries": "off",
        "react-hooks/immutability": "off",
        "react-hooks/preserve-manual-memoization": "off",
        "react-hooks/set-state-in-effect": "off",
    },
}]);
