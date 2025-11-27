{ pkgs, lib, ... }:

{
  home.packages =
    with pkgs;
    [
      bun
      nh
      nixfmt-rfc-style
      opencode
      volta
    ]
    ++ lib.optionals pkgs.stdenv.isLinux [
    ]
    ++ lib.optionals pkgs.stdenv.isDarwin [
    ];
}
