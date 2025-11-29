{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.editors.neovim;

  nvimPlugins = with pkgs.vimPlugins; [
    # UI & Theme
    catppuccin-nvim
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
    which-key-nvim
    gitsigns-nvim

    # Treesitter
    nvim-treesitter.withAllGrammars

    # Fuzzy Finder
    telescope-nvim
    plenary-nvim

    # Formatting
    conform-nvim

    # LSP & Completion
    nvim-lspconfig
    blink-cmp
  ];

  # Lua Configuration
  nvimLuaConfig = ''
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

    -- ==========================================================================
    -- UI & Theme
    -- ==========================================================================
    require('nvim-web-devicons').setup({ default = true })

    require("catppuccin").setup({
      flavour = "mocha",
      transparent_background = true,
      integrations = {
        blink_cmp = true,
        gitsigns = true,
        neotree = true,
        treesitter = true,
        telescope = true,
        which_key = true,
      }
    })
    vim.cmd.colorscheme "catppuccin"

    require('lualine').setup({
      options = {
        theme = 'catppuccin',
        icons_enabled = true,
      }
    })

    -- ==========================================================================
    -- File Management
    -- ==========================================================================
    require("neo-tree").setup({
      close_if_last_window = true,
      window = { position = "left", width = 30 },
      filesystem = {
        follow_current_file = { enabled = true },
        hijack_netrw_behavior = "open_default",
      },
    })

    -- Open Neo-tree on startup if no args
    vim.api.nvim_create_autocmd("VimEnter", {
      desc = "Open Neo-tree on startup",
      callback = function()
        if vim.fn.argc() == 0 then
          vim.cmd("Neotree toggle filesystem reveal left")
        end
      end,
    })

    require("oil").setup()
    vim.keymap.set("n", "-", "<CMD>Oil<CR>", { desc = "Open parent directory" })

    -- ==========================================================================
    -- Editor Essentials
    -- ==========================================================================
    require('gitsigns').setup()
    require('Comment').setup()
    require("which-key").setup()
    require("nvim-surround").setup()
    require("nvim-autopairs").setup()

    -- ==========================================================================
    -- Treesitter
    -- ==========================================================================
    require('nvim-treesitter.configs').setup({
      highlight = { enable = true },
      indent = { enable = true },
    })

    -- ==========================================================================
    -- Fuzzy Finder
    -- ==========================================================================
    local builtin = require('telescope.builtin')
    vim.keymap.set('n', '<leader>ff', builtin.find_files, { desc = 'Find files' })
    vim.keymap.set('n', '<leader>fg', builtin.live_grep, { desc = 'Live grep' })
    vim.keymap.set('n', '<leader>fb', builtin.buffers, { desc = 'Buffers' })
    vim.keymap.set('n', '<leader>fh', builtin.help_tags, { desc = 'Help tags' })

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
        timeout_ms = 500,
      },
    })

    -- ==========================================================================
    -- LSP & Completion
    -- ==========================================================================
    require('blink.cmp').setup({
      keymap = { preset = 'default' },
      appearance = {
        use_nvim_cmp_as_default = true,
        nerd_font_variant = 'mono'
      },
      sources = {
        default = { 'lsp', 'path', 'snippets', 'buffer' },
      },
    })

    local capabilities = require('blink.cmp').get_lsp_capabilities()

    local on_attach = function(client, bufnr)
      local opts = { noremap = true, silent = true, buffer = bufnr }
      vim.keymap.set('n', 'gd', vim.lsp.buf.definition, opts)
      vim.keymap.set('n', 'gr', vim.lsp.buf.references, opts)
      vim.keymap.set('n', 'K', vim.lsp.buf.hover, opts)
      vim.keymap.set('n', '<leader>rn', vim.lsp.buf.rename, opts)
      vim.keymap.set('n', '<leader>ca', vim.lsp.buf.code_action, opts)
    end

    local servers = { 'bashls', 'pyright', 'ts_ls', 'gopls', 'rust_analyzer', 'nixd' }

    for _, server in ipairs(servers) do
      vim.lsp.config(server, {
        on_attach = on_attach,
        capabilities = capabilities,
      })
      vim.lsp.enable(server)
    end
  '';
in
{
  options.modules.editors.neovim = {
    enable = lib.mkEnableOption "neovim configuration";
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

        # Formatters
        stylua
        ruff
        nodePackages.prettier
        nixfmt-rfc-style

        # Tools
        ripgrep
        fd
        tree-sitter
      ];

      extraLuaConfig = nvimLuaConfig;
    };
  };
}
