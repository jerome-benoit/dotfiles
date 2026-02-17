{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.editors.vim;
  vimSettings = ''
    " Base
    set encoding=utf-8
    set backspace=indent,eol,start
    set mouse=a
    set hidden
    set autoread
    set confirm
    if has('clipboard')
      set clipboard=unnamedplus
    endif

    " Security
    set nomodeline
    set modelines=0

    " UI
    set background=dark
    set number
    set relativenumber
    set cursorline
    set scrolloff=8
    set signcolumn=yes
    set laststatus=2
    set showcmd
    set showmatch
    set list
    set listchars=tab:▸\ ,trail:·,nbsp:␣

    " Performance
    set ttyfast
    set lazyredraw
    set updatetime=300
    set regexpengine=1

    " Indentation
    set expandtab
    set shiftwidth=2
    set tabstop=2
    set softtabstop=2
    set autoindent
    set smartindent
    set shiftround

    " Text wrapping
    set wrap
    set linebreak
    set breakindent

    " Splits
    set splitbelow
    set splitright

    " Search
    set incsearch
    set hlsearch
    set ignorecase
    set smartcase

    " Completion
    set wildmenu
    set wildmode=list:longest,full

    " Filetype & Syntax
    filetype plugin indent on
    syntax on

    " Plugins
    let g:airline_theme='night_owl'
    let g:airline#extensions#tabline#enabled = 1
    let g:airline_powerline_fonts = 1

    " Autocommands
    if has("autocmd")
      augroup VimConfig
        autocmd!
        autocmd FileType c,cpp,h set tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
        autocmd BufReadPost * if line("'\"") > 0 && line("'\"") <= line("$") | exe "normal! g`\"" | endif
      augroup END
    endif

    " Keymaps
    nnoremap <silent> <Esc> :nohlsearch<CR>
    nnoremap <C-h> <C-w>h
    nnoremap <C-j> <C-w>j
    nnoremap <C-k> <C-w>k
    nnoremap <C-l> <C-w>l
    vnoremap < <gv
    vnoremap > >gv
  '';
  vimPlugins = [
    pkgs.vimPlugins.vim-airline
    pkgs.vimPlugins.vim-airline-themes
    pkgs.vimPlugins.vim-nix
    pkgs.vimPlugins.vim-commentary
    pkgs.vimPlugins.vim-surround
    pkgs.vimPlugins.vim-gitgutter
  ];

in
{
  options.modules.editors.vim = {
    enable = lib.mkEnableOption "vim configuration";
  };

  config = lib.mkIf cfg.enable {
    # On Linux, we use the system vim, so we just generate the .vimrc
    home.file.".vimrc" = lib.mkIf pkgs.stdenv.isLinux {
      text = ''
        set nocompatible
        ${lib.concatMapStringsSep "\n" (p: "set rtp^=${p}") vimPlugins}

        ${vimSettings}
      '';
    };

    # On Darwin, we use Home Manager's vim module
    programs.vim = lib.mkIf pkgs.stdenv.isDarwin {
      enable = true;
      plugins = vimPlugins;
      extraConfig = vimSettings;
    };
  };
}
