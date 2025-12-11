{
  systems = {
    linux = {
      name = "linux";
      arch = "x86_64-linux";
    };
    darwin = {
      name = "darwin";
      arch = "aarch64-darwin";
    };
  };

  profiles = {
    desktop = "desktop";
    server = "server";
  };

  distros = {
    almalinux = "almalinux";
    debian = "debian";
    fedora = "fedora";
    ubuntu = "ubuntu";
  };
}
