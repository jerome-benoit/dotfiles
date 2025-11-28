{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.editors.neovim;

  nvimPlugins = with pkgs.vimPlugins; [
    # Core / Quality of Life
    nvim-surround
    nvim-autopairs
    comment-nvim
    which-key-nvim
    gitsigns-nvim

    # UI / Aesthetics
    catppuccin-nvim
    lualine-nvim
    nvim-web-devicons

    # Treesitter
    nvim-treesitter.withAllGrammars

    # Fuzzy Finder
    telescope-nvim
    plenary-nvim

    # LSP & Completion
    nvim-lspconfig
    nvim-cmp
    cmp-nvim-lsp
    cmp-buffer
    cmp-path
    cmp-cmdline
    luasnip
    cmp_luasnip
    friendly-snippets

    # Formatting
    conform-nvim
  ];

  # Lua Configuration
  nvimLuaConfig = ''
    -- Options
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

    -- Theme: Catppuccin
    require("catppuccin").setup({
      flavour = "mocha",
      transparent_background = true,
      integrations = {
        cmp = true,
        gitsigns = true,
        nvimtree = true,
        treesitter = true,
        telescope = true,
        which_key = true,
      }
    })

    -- Icons
    require('nvim-web-devicons').setup({
      default = true;
    })

    vim.cmd.colorscheme "catppuccin"

    -- Lualine
    require('lualine').setup({
      options = {
        theme = 'catppuccin',
        icons_enabled = true,
      }
    })

    -- Gitsigns
    require('gitsigns').setup()

    -- Comment.nvim
    require('Comment').setup()

    -- Which-key
    require("which-key").setup()

    -- Surround
    require("nvim-surround").setup()

    -- Autopairs
    require("nvim-autopairs").setup()

    -- Treesitter
    require('nvim-treesitter.configs').setup({
      highlight = { enable = true },
      indent = { enable = true },
    })

    -- Telescope
    local builtin = require('telescope.builtin')
    vim.keymap.set('n', '<leader>ff', builtin.find_files, { desc = 'Find files' })
    vim.keymap.set('n', '<leader>fg', builtin.live_grep, { desc = 'Live grep' })
    vim.keymap.set('n', '<leader>fb', builtin.buffers, { desc = 'Buffers' })
    vim.keymap.set('n', '<leader>fh', builtin.help_tags, { desc = 'Help tags' })

    -- Formatting (Conform)
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

    -- Completion (nvim-cmp)
    local cmp = require('cmp')
    local luasnip = require('luasnip')

    require("luasnip.loaders.from_vscode").lazy_load()

    cmp.setup({
      snippet = {
        expand = function(args)
          luasnip.lsp_expand(args.body)
        end,
      },
      mapping = cmp.mapping.preset.insert({
        ['<C-b>'] = cmp.mapping.scroll_docs(-4),
        ['<C-f>'] = cmp.mapping.scroll_docs(4),
        ['<C-Space>'] = cmp.mapping.complete(),
        ['<C-e>'] = cmp.mapping.abort(),
        ['<CR>'] = cmp.mapping.confirm({ select = true }),
        ['<Tab>'] = cmp.mapping(function(fallback)
          if cmp.visible() then
            cmp.select_next_item()
          elseif luasnip.expand_or_jumpable() then
            luasnip.expand_or_jump()
          else
            fallback()
          end
        end, { 'i', 's' }),
        ['<S-Tab>'] = cmp.mapping(function(fallback)
          if cmp.visible() then
            cmp.select_prev_item()
          elseif luasnip.jumpable(-1) then
            luasnip.jump(-1)
          else
            fallback()
          end
        end, { 'i', 's' }),
      }),
      sources = cmp.config.sources({
        { name = 'nvim_lsp' },
        { name = 'luasnip' },
      }, {
        { name = 'buffer' },
        { name = 'path' },
      })
    })

    -- LSP Config
    local capabilities = require('cmp_nvim_lsp').default_capabilities()

    local on_attach = function(client, bufnr)
      local opts = { noremap = true, silent = true, buffer = bufnr }
      vim.keymap.set('n', 'gd', vim.lsp.buf.definition, opts)
      vim.keymap.set('n', 'gr', vim.lsp.buf.references, opts)
      vim.keymap.set('n', 'K', vim.lsp.buf.hover, opts)
      vim.keymap.set('n', '<leader>rn', vim.lsp.buf.rename, opts)
      vim.keymap.set('n', '<leader>ca', vim.lsp.buf.code_action, opts)
    end

    -- List of servers to setup
    -- Ensure these are installed via extraPackages or system
    local servers = { 'bashls', 'pyright', 'ts_ls', 'gopls', 'rust_analyzer', 'nil_ls' }

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
        nil # Nix LSP

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
