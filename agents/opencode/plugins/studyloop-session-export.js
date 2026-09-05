// studyloop:session-export-hook
// OpenCode global plugin: export after the session reaches idle.
export const StudyLoopSessionExport = async ({ $ }) => ({
  event: async ({ event }) => {
    if (event.type !== "session.idle") return
    try {
      await $`session-export --opencode-only`
    } catch {
      // Export is a safety net; it must never trap the user in OpenCode.
    }
  },
})
