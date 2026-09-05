// studyloop:session-export-hook
// pi global extension: session_shutdown is emitted for quit, new, resume,
// fork, and clone transitions. Export is best-effort and must never block exit.
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

export default function studyLoopSessionExport(pi: ExtensionAPI) {
  pi.on("session_shutdown", async (_event, ctx) => {
    await ctx.exec("session-export", ["--pi-only"], { timeout: 30_000 }).catch(() => undefined);
  });
}
