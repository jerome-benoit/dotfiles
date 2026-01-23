{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.modules.editors.neovim;

  nvimAiPluginOpencode = pkgs.vimUtils.buildVimPlugin {
    pname = "opencode-nvim";
    version = "unstable-${lib.substring 0 9 inputs.opencode-nvim.rev}";
    src = inputs.opencode-nvim;
    meta = with lib; {
      homepage = "https://github.com/NickvanDyke/opencode.nvim";
      description = "OpenCode integration for Neovim";
      license = licenses.mit;
      maintainers = [ ];
    };
  };

  nvimBasePlugins = with pkgs.vimPlugins; [
    # UI & Theme
    snacks-nvim
    tokyonight-nvim
    lualine-nvim
    nvim-web-devicons

    # File Management
    neo-tree-nvim
    nui-nvim
    oil-nvim

    # Editor Essentials
    nvim-surround
    nvim-autopairs
    comment-nvim
    nvim-ts-context-commentstring
    which-key-nvim
    gitsigns-nvim

    # Treesitter
    nvim-treesitter.withAllGrammars
    nvim-treesitter-textobjects

    # Fuzzy Finder
    telescope-nvim
    telescope-fzf-native-nvim
    plenary-nvim

    # Formatting
    conform-nvim

    # LSP & Completion
    blink-cmp
    friendly-snippets
    lazydev-nvim
  ];

  nvimAiPlugins = [ nvimAiPluginOpencode ];

  nvimPlugins = nvimBasePlugins ++ lib.optionals cfg.plugins.opencode.enable nvimAiPlugins;

  nvimBaseLuaConfig = ''
    -- Global Options
    vim.o.termguicolors = true
    vim.o.number, vim.o.relativenumber = true, true
    vim.o.cursorline, vim.o.scrolloff = true, 5
    vim.o.expandtab, vim.o.shiftwidth, vim.o.tabstop = true, 2, 2
    vim.o.smartindent, vim.o.ignorecase, vim.o.smartcase = true, true, true
    vim.o.clipboard, vim.o.updatetime, vim.o.timeoutlen = 'unnamedplus', 250, 300
    vim.o.signcolumn, vim.o.autoread, vim.o.undofile = 'yes', true, true
    vim.o.mouse, vim.o.splitright, vim.o.splitbelow = 'a', true, true

    -- UI & Theme
    require('nvim-web-devicons').setup({ default = true })
    require("snacks").setup({
      bigfile = { enabled = true }, dashboard = { enabled = true }, indent = { enabled = true },
      input = { enabled = true }, notifier = { enabled = true }, picker = { enabled = true },
      quickfile = { enabled = true }, scroll = { enabled = true }, statuscolumn = { enabled = true },
      terminal = { enabled = true }, words = { enabled = true },
    })
    require("tokyonight").setup({
      style = "storm", transparent = true, terminal_colors = true,
      styles = { comments = { italic = true }, keywords = { italic = true }, functions = {}, variables = {}, sidebars = "dark", floats = "dark" },
      cache = true,
    })
    vim.cmd.colorscheme "tokyonight-storm"

    -- File Management
    require("neo-tree").setup({
      close_if_last_window = true, window = { position = "left", width = 30 },
      filesystem = { follow_current_file = { enabled = true }, hijack_netrw_behavior = "open_default", use_libuv_file_watcher = true },
    })
    vim.api.nvim_create_autocmd("VimEnter", {
      group = vim.api.nvim_create_augroup("NeotreeAuto", { clear = true }),
      callback = function() if vim.fn.argc() == 0 then vim.cmd("Neotree toggle filesystem reveal left") end end,
    })
    vim.keymap.set("n", "<leader>e", "<CMD>Neotree toggle<CR>", { desc = "File explorer: Toggle", silent = true })
    require("oil").setup({ watch_for_changes = true, view_options = { show_hidden = true } })
    vim.keymap.set("n", "<leader>-", "<CMD>Oil<CR>", { desc = "File explorer: Parent directory", silent = true })

    -- Editor Essentials
    require('gitsigns').setup({ watch_gitdir = { interval = 1000, follow_files = true } })
    require('ts_context_commentstring').setup({ enable_autocmd = false })
    require('Comment').setup({ pre_hook = require('ts_context_commentstring.integrations.comment_nvim').create_pre_hook() })
    require("which-key").setup({ preset = "modern" })
    require("nvim-surround").setup()
    require("nvim-autopairs").setup()

    -- Treesitter
    require('nvim-treesitter').setup({
      highlight = { enable = true },
      indent = { enable = true },
      incremental_selection = {
        enable = true,
        keymaps = {
          init_selection = 'gnn',
          node_incremental = 'grn',
          node_decremental = 'grm',
          scope_incremental = 'grc',
        },
      },
    })

    -- Treesitter Textobjects
    require('nvim-treesitter-textobjects').setup({
      select = {
        enable = true,
        lookahead = true,
        keymaps = {
          ["af"] = "@function.outer",
          ["if"] = "@function.inner",
          ["ac"] = "@class.outer",
          ["ic"] = "@class.inner",
          ["aa"] = "@parameter.outer",
          ["ia"] = "@parameter.inner",
          ["ab"] = "@block.outer",
          ["ib"] = "@block.inner",
          ["ai"] = "@conditional.outer",
          ["ii"] = "@conditional.inner",
          ["al"] = "@loop.outer",
          ["il"] = "@loop.inner",
          ["a/"] = "@comment.outer",
          ["i/"] = "@comment.outer",
          ["ak"] = "@call.outer",
          ["ik"] = "@call.inner",
        },
        selection_modes = {
          ['@parameter.outer'] = 'v',
          ['@function.outer'] = 'V',
          ['@class.outer'] = '<c-v>',
        },
        include_surrounding_whitespace = true,
      },
      move = {
        enable = true,
        set_jumps = true,
        goto_next_start = {
          ["]f"] = "@function.outer",
          ["]c"] = "@class.outer",
          ["]a"] = "@parameter.inner",
          ["]i"] = "@conditional.outer",
          ["]l"] = "@loop.outer",
          ["]/"] = "@comment.outer",
        },
        goto_next_end = {
          ["]F"] = "@function.outer",
          ["]C"] = "@class.outer",
          ["]A"] = "@parameter.inner",
          ["]I"] = "@conditional.outer",
          ["]L"] = "@loop.outer",
        },
        goto_previous_start = {
          ["[f"] = "@function.outer",
          ["[c"] = "@class.outer",
          ["[a"] = "@parameter.inner",
          ["[i"] = "@conditional.outer",
          ["[l"] = "@loop.outer",
          ["[/"] = "@comment.outer",
        },
        goto_previous_end = {
          ["[F"] = "@function.outer",
          ["[C"] = "@class.outer",
          ["[A"] = "@parameter.inner",
          ["[I"] = "@conditional.outer",
          ["[L"] = "@loop.outer",
        },
      },
      swap = {
        enable = true,
        swap_next = {
          ["<leader>sn"] = "@parameter.inner",
        },
        swap_previous = {
          ["<leader>sp"] = "@parameter.inner",
        },
      },
    })

    -- Telescope
    require('telescope').setup({})
    require('telescope').load_extension('fzf')
    local tb = require('telescope.builtin')
    vim.keymap.set('n', '<leader>ff', tb.find_files, { desc = "Find: Files", silent = true })
    vim.keymap.set('n', '<leader>fg', tb.live_grep, { desc = "Find: Text (grep)", silent = true })
    vim.keymap.set('n', '<leader>fb', tb.buffers, { desc = "Find: Buffers", silent = true })
    vim.keymap.set('n', '<leader>fh', tb.help_tags, { desc = "Find: Help tags", silent = true })
    vim.keymap.set('n', '<leader>fr', tb.oldfiles, { desc = "Find: Recent files", silent = true })
    vim.keymap.set('n', '<leader>/', tb.current_buffer_fuzzy_find, { desc = "Find: In buffer", silent = true })

    -- Formatting
    require("conform").setup({
      formatters_by_ft = {
        lua = { "stylua" },
        python = { "ruff_format", "ruff_fix" },
        javascript = { "prettier" },
        typescript = { "prettier" },
        javascriptreact = { "prettier" },
        typescriptreact = { "prettier" },
        nix = { "nixfmt" },
        markdown = { "prettier" },
        json = { "prettier" },
        yaml = { "prettier" },
      },
      format_on_save = {
        lsp_format = "fallback",
        timeout_ms = 500,
      },
    })

    -- LSP & Completion
    require("lazydev").setup()
    require('blink.cmp').setup({
      completion = {
        menu = {
          border = 'rounded',
          scrollbar = true,
        },
        documentation = {
          window = {
            border = 'rounded',
          },
          auto_show_delay_ms = 200,
        },
      },
      sources = {
        default = { 'lsp', 'path', 'snippets', 'buffer', 'lazydev' },
        providers = {
          lazydev = {
            name = "LazyDev",
            module = "lazydev.integrations.blink",
            score_offset = 100,
          },
        },
      },
    })
    local lsp_capabilities = require('blink.cmp').get_lsp_capabilities()

    -- LSP keymaps
    local lsp_on_attach = function(client, bufnr)
      local function lsp_opts(desc)
        return { desc = desc, buffer = bufnr, silent = true }
      end
      vim.keymap.set('n', 'gd', vim.lsp.buf.definition, lsp_opts("LSP: Definition"))
      vim.keymap.set('n', 'gD', vim.lsp.buf.declaration, lsp_opts("LSP: Declaration"))
      vim.keymap.set('n', 'gi', vim.lsp.buf.implementation, lsp_opts("LSP: Implementation"))
      vim.keymap.set('n', 'gt', vim.lsp.buf.type_definition, lsp_opts("LSP: Type definition"))
      vim.keymap.set('n', 'gr', vim.lsp.buf.references, lsp_opts("LSP: References"))
      vim.keymap.set('n', 'K', vim.lsp.buf.hover, lsp_opts("LSP: Hover"))
      vim.keymap.set('n', '<leader>rn', vim.lsp.buf.rename, lsp_opts("LSP: Rename"))
      vim.keymap.set({ 'n', 'v' }, '<leader>ca', vim.lsp.buf.code_action, lsp_opts("LSP: Code action"))
      vim.keymap.set('n', '<leader>d', vim.diagnostic.open_float, lsp_opts("LSP: Show diagnostic"))
      vim.keymap.set('n', '[d', vim.diagnostic.goto_prev, lsp_opts("LSP: Previous diagnostic"))
      vim.keymap.set('n', ']d', vim.diagnostic.goto_next, lsp_opts("LSP: Next diagnostic"))
    end

    -- LSP diagnostics
    local signs = { Error = " ", Warn = " ", Hint = "󰠠 ", Info = " " }
    for type, icon in pairs(signs) do
      local hl = "DiagnosticSign" .. type
      vim.fn.sign_define(hl, { text = icon, texthl = hl, numhl = "" })
    end

    vim.diagnostic.config({
      virtual_text = {
        prefix = "●",
        spacing = 4,
      },
      float = {
        border = "rounded",
        source = "always",
        header = "",
        prefix = "",
      },
    })

    -- LSP servers (Neovim 0.11+ API)
    vim.lsp.config('*', {
      capabilities = lsp_capabilities,
      on_attach = lsp_on_attach,
    })

    vim.lsp.enable({ 'bashls', 'pyright', 'ts_ls', 'gopls', 'rust_analyzer', 'nixd', 'lua_ls' })
  '';

  nvimOpencodeConfig = lib.optionalString cfg.plugins.opencode.enable ''
    -- OpenCode AI Integration
    vim.g.opencode_opts = {
      provider = {
        enabled = "snacks",
        snacks = {
          auto_close = true,
          win = {
            position = "right",
            enter = false,
            wo = {
              winbar = "",
            },
            bo = {
              filetype = "opencode_terminal",
            },
          },
        },
      },
      events = {
        enabled = true,
        reload = true,
        permissions = {
          enabled = true,
          idle_delay_ms = 1000,
        },
      },
      ask = {
        prompt = "Ask opencode: ",
        blink_cmp_sources = { "opencode", "buffer" },
      },
      prompts = {
        ask_append = { prompt = "", ask = true },
        ask_this = { prompt = "@this: ", ask = true, submit = true },
        diagnostics = { prompt = "Explain @diagnostics", submit = true },
        diff = { prompt = "Review the following git diff for correctness and readability: @diff", submit = true },
        document = { prompt = "Add comments documenting @this", submit = true },
        explain = { prompt = "Explain @this and its context", submit = true },
        fix = { prompt = "Fix @diagnostics", submit = true },
        implement = { prompt = "Implement @this", submit = true },
        optimize = { prompt = "Optimize @this for performance and readability", submit = true },
        review = { prompt = "Review @this for correctness and readability", submit = true },
        test = { prompt = "Add tests for @this", submit = true },
        nix = { prompt = "Review @this for Nix best practices", submit = true },
        security = { prompt = "Review @this for security vulnerabilities", submit = true },
        marks = { prompt = "List @marks with locations", submit = true },
      },
    }

    local opencode_map = vim.keymap.set
    opencode_map({ "n", "x" }, "<leader>oa", function() require("opencode").ask("@this: ", { submit = true }) end, { desc = "OpenCode: Ask question", silent = true })
    opencode_map({ "n", "x" }, "<leader>om", function() require("opencode").select() end, { desc = "OpenCode: Menu", silent = true })
    opencode_map({ "n", "t" }, "<leader>ot", function() require("opencode").toggle() end, { desc = "OpenCode: Toggle terminal", silent = true })
    opencode_map({ "n", "x" }, "go", function() return require("opencode").operator("@this ") end, { expr = true, desc = "OpenCode: Add range to prompt" })
    opencode_map("n", "goo", function() return require("opencode").operator("@this ") .. "_" end, { expr = true, desc = "OpenCode: Add line to prompt" })

    opencode_map("n", "<leader>osl", function() require("opencode").command("session.list") end, { desc = "OpenCode Session: List", silent = true })
    opencode_map("n", "<leader>osn", function() require("opencode").command("session.new") end, { desc = "OpenCode Session: New", silent = true })
    opencode_map("n", "<leader>osh", function() require("opencode").command("session.share") end, { desc = "OpenCode Session: Share", silent = true })
    opencode_map("n", "<leader>osi", function() require("opencode").command("session.interrupt") end, { desc = "OpenCode Session: Interrupt", silent = true })
    opencode_map("n", "<leader>osc", function() require("opencode").command("session.compact") end, { desc = "OpenCode Session: Compact", silent = true })
    opencode_map("n", "<leader>osu", function() require("opencode").command("session.undo") end, { desc = "OpenCode Session: Undo", silent = true })
    opencode_map("n", "<leader>osr", function() require("opencode").command("session.redo") end, { desc = "OpenCode Session: Redo", silent = true })

    opencode_map("n", "<leader>onj", function() require("opencode").command("session.half.page.down") end, { desc = "OpenCode Nav: Scroll down", silent = true })
    opencode_map("n", "<leader>onk", function() require("opencode").command("session.half.page.up") end, { desc = "OpenCode Nav: Scroll up", silent = true })
    opencode_map("n", "<leader>onJ", function() require("opencode").command("session.page.down") end, { desc = "OpenCode Nav: Page down", silent = true })
    opencode_map("n", "<leader>onK", function() require("opencode").command("session.page.up") end, { desc = "OpenCode Nav: Page up", silent = true })
    opencode_map("n", "<leader>ong", function() require("opencode").command("session.first") end, { desc = "OpenCode Nav: First message", silent = true })
    opencode_map("n", "<leader>onG", function() require("opencode").command("session.last") end, { desc = "OpenCode Nav: Last message", silent = true })

    opencode_map("n", "<leader>ops", function() require("opencode").command("prompt.submit") end, { desc = "OpenCode Prompt: Submit", silent = true })
    opencode_map("n", "<leader>opc", function() require("opencode").command("prompt.clear") end, { desc = "OpenCode Prompt: Clear", silent = true })

    opencode_map("n", "<leader>oc", function() require("opencode").command("agent.cycle") end, { desc = "OpenCode: Cycle agent", silent = true })

    local wk = require("which-key")
    wk.add({
      { "<leader>o", group = "OpenCode" },
      { "<leader>os", group = "Session" },
      { "<leader>on", group = "Navigation" },
      { "<leader>op", group = "Prompt" },
    })

    local opencode_events_group = vim.api.nvim_create_augroup("OpencodeEvents", { clear = true })
    vim.api.nvim_create_autocmd("User", {
      group = opencode_events_group,
      pattern = "OpencodeEvent:*",
      callback = function(args)
        local opencode_event = args.data.event
        if opencode_event.type == "session.idle" then
          vim.notify("OpenCode ready", vim.log.levels.INFO)
        elseif opencode_event.type == "session.error" then
          vim.notify("OpenCode error: " .. vim.inspect(opencode_event.data), vim.log.levels.ERROR)
        end
      end,
    })
  '';

  nvimLualineConfig = ''
    require('lualine').setup({
      options = {
        theme = 'tokyonight',
        icons_enabled = true,
        component_separators = { left = "", right = ""},
        section_separators = { left = "", right = ""},
      },
      sections = {
        lualine_a = { 'mode' },
        lualine_b = { 'branch', 'diff', 'diagnostics' },
        lualine_c = {
          {
            'filename',
            path = 1,
            symbols = {
              modified = '[+]',
              readonly = '[-]',
              unnamed = '[No Name]',
            }
          }
        },
        lualine_x = { 'encoding', 'fileformat', 'filetype' },
        lualine_y = { 'progress' },
        lualine_z = { 'location'${lib.optionalString cfg.plugins.opencode.enable ", { require('opencode').statusline }"} }
      },
      inactive_sections = {
        lualine_c = { 'filename' },
        lualine_x = { 'location' },
      },
    })
  '';

  nvimLuaConfig = nvimBaseLuaConfig + nvimOpencodeConfig + nvimLualineConfig;
in
{
  options.modules.editors.neovim = {
    enable = lib.mkEnableOption "neovim configuration";
    plugins = {
      opencode.enable = lib.mkEnableOption "opencode.nvim integration";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.plugins.opencode.enable -> config.modules.development.opencode.enable;
        message = "Neovim opencode integration requires opencode module enabled (modules.development.opencode.enable = true)";
      }
    ];

    programs.neovim = {
      enable = true;
      viAlias = false;
      vimAlias = false;
      withNodeJs = true;
      withPython3 = true;

      plugins = nvimPlugins;

      extraPackages =
        with pkgs;
        [
          # LSP Servers
          nodePackages.bash-language-server
          pyright
          nodePackages.typescript-language-server
          gopls
          rust-analyzer
          nixd
          lua-language-server

          # Formatters
          stylua
          nodePackages.prettier
          nixfmt
          ruff

          # Tools
          tree-sitter
        ]
        ++ lib.optionals cfg.plugins.opencode.enable (
          lib.optional (
            config.modules.development.opencode.opencodePackage != null
          ) config.modules.development.opencode.opencodePackage
        );

      initLua = nvimLuaConfig;
    };
  };
}
