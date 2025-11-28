{ pkgs, lib, ... }:

let
  # Common configuration
  vimSettings = ''
    " --- General settings ---
    syntax on
    set backspace=indent,eol,start
    set encoding=utf-8
    set mouse=a

    " --- UI settings ---
    set background=dark
    set number
    set relativenumber
    set cursorline          " Highlight current line
    set scrolloff=5         " Keep 5 lines above/below cursor

    " --- Indentation settings ---
    set expandtab           " Use spaces instead of tabs
    set shiftwidth=2        " Size of an indent
    set tabstop=2           " Number of spaces tabs count for
    set autoindent          " Copy indent from current line when starting a new line

    " --- Search settings ---
    set incsearch           " Incremental search
    set hlsearch            " Highlight search results
    set ignorecase          " Ignore case when searching...
    set smartcase           " ...unless uppercase letters are used

    " --- Plugin settings ---
    " Airline
    let g:airline#extensions#tabline#enabled = 1
    let g:airline_powerline_fonts = 1

    " --- Filetype settings ---
    " Enable filetype detection, plugins and indentation
    filetype plugin indent on

    if has("autocmd")
      " Indent with four spaces C, C++ files
      autocmd FileType c,cpp,h set tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
    endif
  '';
  vimPlugins = with pkgs.vimPlugins; [
    vim-airline
    vim-airline-themes
    vim-nix
    vim-commentary
    vim-surround
    vim-gitgutter
  ];

in
{
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
}
