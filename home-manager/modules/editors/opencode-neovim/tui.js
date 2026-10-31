// Dispatch Neovim's private OSC transport without changing the user's TUI keybinds.
export default {
  id: "neovim-terminal",
  setup(context) {
    if (!process.env.NVIM_OPENCODE_COMMANDS) return
    const commands = JSON.parse(process.env.NVIM_OPENCODE_COMMANDS)
    const input = (sequence) => {
      const match = /^\x1b\]777;opencode-neovim-command;(\d+)(?:\x07|\x1b\\)$/.exec(sequence)
      if (!match) return false
      const command = commands[Number(match[1]) - 1]
      const target = context.keymap.commands().find((item) => item.id === command)
      const enabled = typeof target?.enabled === "function" ? target.enabled() : target?.enabled
      if (!target || enabled === false) {
        context.ui.toast.show({ message: `OpenCode action unavailable here: ${command}`, variant: "error" })
        return true
      }
      try {
        context.keymap.dispatch(command)
      } catch (error) {
        context.ui.toast.show({ message: String(error), variant: "error" })
      }
      return true
    }
    context.renderer.prependInputHandler(input)
    // Neovim must not send commands before the TUI has registered this handler.
    process.stdout.write("\x1b]777;opencode-neovim-ready\x07")
    return () => {
      context.renderer.removeInputHandler(input)
      process.stdout.write("\x1b]777;opencode-neovim-stop\x07")
    }
  },
}
