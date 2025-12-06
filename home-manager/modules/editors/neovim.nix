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
    name = "opencode-nvim";
    src = inputs.opencode-nvim;
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

  nvimPlugins = nvimBasePlugins ++ lib.optionals cfg.opencode.enable nvimAiPlugins;

  # Lua Configuration
  nvimBaseLuaConfig = ''
    -- ==========================================================================
    -- Global Options
    -- ==========================================================================
    vim.o.termguicolors = true
    vim.o.number = true
    vim.o.relativenumber = true
    vim.o.cursorline = true
    vim.o.scrolloff = 5
    vim.o.expandtab = true
    vim.o.shiftwidth = 2
    vim.o.tabstop = 2
    vim.o.smartindent = true
    vim.o.ignorecase = true
    vim.o.smartcase = true
    vim.o.clipboard = 'unnamedplus'
    vim.o.updatetime = 250
    vim.o.timeoutlen = 300
    vim.o.signcolumn = 'yes'
    vim.o.autoread = true
    vim.o.undofile = true
    vim.o.mouse = 'a'
    vim.o.splitright = true
    vim.o.splitbelow = true

    -- ==========================================================================
    -- UI & Theme
    -- ==========================================================================
    require('nvim-web-devicons').setup({ default = true })

    require("snacks").setup({
      bigfile = { enabled = true },
      dashboard = { enabled = true },
      indent = { enabled = true },
      input = { enabled = true },
      notifier = { enabled = true },
      picker = { enabled = true },
      quickfile = { enabled = true },
      scroll = { enabled = true },
      statuscolumn = { enabled = true },
      terminal = { enabled = true },
      words = { enabled = true },
    })

    require("tokyonight").setup({
      style = "storm",
      transparent = true,
      terminal_colors = true,
      styles = {
        comments = { italic = true },
        keywords = { italic = true },
        functions = {},
        variables = {},
        sidebars = "dark",
        floats = "dark",
      },
      cache = true,
    })
    vim.cmd.colorscheme "tokyonight-storm"

    -- ==========================================================================
    -- File Management
    -- ==========================================================================
    require("neo-tree").setup({
      close_if_last_window = true,
      window = { position = "left", width = 30 },
      filesystem = {
        follow_current_file = { enabled = true },
        hijack_netrw_behavior = "open_default",
        use_libuv_file_watcher = true,
      },
    })

    -- Open Neo-tree on startup if no args
    local neotree_auto_group = vim.api.nvim_create_augroup("NeotreeAuto", { clear = true })
    vim.api.nvim_create_autocmd("VimEnter", {
      group = neotree_auto_group,
      desc = "Open Neo-tree on startup",
      callback = function()
        if vim.fn.argc() == 0 then
          vim.cmd("Neotree toggle filesystem reveal left")
        end
      end,
    })
    vim.keymap.set("n", "<leader>e", "<CMD>Neotree toggle<CR>", { desc = "File explorer: Toggle", silent = true })

    require("oil").setup({
      watch_for_changes = true,
      view_options = {
        show_hidden = true,
      },
    })
    vim.keymap.set("n", "<leader>-", "<CMD>Oil<CR>", { desc = "File explorer: Parent directory", silent = true })

    -- ==========================================================================
    -- Editor Essentials
    -- ==========================================================================
    require('gitsigns').setup({
      watch_gitdir = {
        interval = 1000,
        follow_files = true,
      },
    })
    require('ts_context_commentstring').setup({
      enable_autocmd = false,
    })
    require('Comment').setup({
      pre_hook = require('ts_context_commentstring.integrations.comment_nvim').create_pre_hook(),
    })
    require("which-key").setup({
      preset = "modern",
    })
    require("nvim-surround").setup()
    require("nvim-autopairs").setup()

    -- ==========================================================================
    -- Treesitter
    -- ==========================================================================
    require('nvim-treesitter.configs').setup({
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
      textobjects = {
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
          },
          goto_next_end = {
            ["]F"] = "@function.outer",
            ["]C"] = "@class.outer",
            ["]A"] = "@parameter.inner",
          },
          goto_previous_start = {
            ["[f"] = "@function.outer",
            ["[c"] = "@class.outer",
            ["[a"] = "@parameter.inner",
          },
          goto_previous_end = {
            ["[F"] = "@function.outer",
            ["[C"] = "@class.outer",
            ["[A"] = "@parameter.inner",
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
      },
    })

    -- ==========================================================================
    -- Fuzzy Finder
    -- ==========================================================================
    require('telescope').setup({
      extensions = {
        fzf = {
          fuzzy = true,
          override_generic_sorter = true,
          override_file_sorter = true,
          case_mode = "smart_case",
        }
      }
    })
    require('telescope').load_extension('fzf')

    local telescope_builtin = require('telescope.builtin')
    vim.keymap.set('n', '<leader>ff', telescope_builtin.find_files, { desc = "Find: Files", silent = true })
    vim.keymap.set('n', '<leader>fg', telescope_builtin.live_grep, { desc = "Find: Text (grep)", silent = true })
    vim.keymap.set('n', '<leader>fb', telescope_builtin.buffers, { desc = "Find: Buffers", silent = true })
    vim.keymap.set('n', '<leader>fh', telescope_builtin.help_tags, { desc = "Find: Help tags", silent = true })

    -- ==========================================================================
    -- Formatting
    -- ==========================================================================
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
        lsp_fallback = true,
        timeout_ms = 2000,
      },
    })

    -- ==========================================================================
    -- LSP & Completion
    -- ==========================================================================
    require("lazydev").setup()

    require('blink.cmp').setup({
      keymap = { preset = 'default' },
      appearance = {
        nerd_font_variant = 'mono'
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

    -- LSP servers (Neovim 0.11+ API)
    vim.lsp.config('*', {
      capabilities = lsp_capabilities,
      on_attach = lsp_on_attach,
    })

    vim.lsp.enable({ 'bashls', 'pyright', 'ts_ls', 'gopls', 'rust_analyzer', 'nixd', 'lua_ls' })
  '';

  nvimOpencodeConfig = lib.optionalString cfg.opencode.enable ''
    -- ==========================================================================
    -- AI
    -- ==========================================================================

    vim.g.opencode_opts = {
      provider = {
        enabled = "snacks",
        snacks = {
          win = {
            style = "terminal"
          }
        }
      },
      events = {
        enabled = true,
        reload = true,
      },
      prompts = {
        nix = "Review @this for Nix best practices and suggest improvements",
        security = "Review @this for security vulnerabilities",
        diagnostics = "Explain @diagnostics",
        diff = "Review the following git diff for correctness and readability: @diff",
        document = "Add comments documenting @this",
        explain = "Explain @this and its context",
        fix = "Fix @diagnostics",
        optimize = "Optimize @this for performance and readability",
        review = "Review @this for correctness and readability",
        test = "Add tests for @this",
      }
    }

    local opencode_map = vim.keymap.set
    opencode_map({ "n", "x" }, "<leader>oa", function() require("opencode").ask("@this: ", { submit = true }) end, { desc = "OpenCode: Ask question", silent = true })
    opencode_map({ "n", "x" }, "<leader>os", function() require("opencode").select() end, { desc = "OpenCode: Actions menu", silent = true })
    opencode_map({ "n", "x" }, "<leader>op", function() require("opencode").prompt("@this") end, { desc = "OpenCode: Add to prompt", silent = true })
    opencode_map({ "n", "t" }, "<leader>ot", function() require("opencode").toggle() end, { desc = "OpenCode: Toggle terminal", silent = true })
    opencode_map("n", "<leader>ou", function() require("opencode").command("session.half.page.up") end, { desc = "OpenCode: Session scroll up", silent = true })
    opencode_map("n", "<leader>od", function() require("opencode").command("session.half.page.down") end, { desc = "OpenCode: Session scroll down", silent = true })

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
      },
      sections = {
        lualine_c = {
          { 'filename', path = 1 }
        }${lib.optionalString cfg.opencode.enable ",\n        lualine_z = {\n          { require(\"opencode\").statusline }\n        }"}
      }
    })
  '';

  nvimLuaConfig = nvimBaseLuaConfig + nvimOpencodeConfig + nvimLualineConfig;
in
{
  options.modules.editors.neovim = {
    enable = lib.mkEnableOption "neovim configuration";
    opencode.enable = lib.mkEnableOption "opencode.nvim integration";
  };

  config = lib.mkIf cfg.enable {
    programs.neovim = {
      enable = true;
      viAlias = false;
      vimAlias = false;
      withNodeJs = true;
      withPython3 = true;

      plugins = nvimPlugins;

      extraPackages = with pkgs; [
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
        nixfmt-rfc-style
        ruff

        # Tools
        tree-sitter
      ];

      extraLuaConfig = nvimLuaConfig;
    };
  };
}
