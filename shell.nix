{ pkgs ? import <nixpkgs> {} }:

let
  pythonEnv = pkgs.python313.withPackages (ps: with ps; [
    pip
    virtualenv
  ]);
  
  deps = with pkgs; [
    stdenv.cc.cc.lib
    zlib
    glib
    dbus
    atk
    pango
    freetype
    fontconfig
    libxkbcommon
    libxml2
    libuuid
    # X11/XCB libs
    xorg.libX11
    xorg.libXcomposite
    xorg.libXdamage
    xorg.libXext
    xorg.libXfixes
    xorg.libXrandr
    xorg.libxcb
    xorg.libXrender
    # Others
    libgbm
    expat
    nss
    nspr
    alsa-lib
    at-spi2-core
    cups
    libdrm
    mesa
  ];
in
pkgs.mkShell {
  buildInputs = [ pythonEnv ] ++ deps;

  shellHook = ''
    export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath deps}:$LD_LIBRARY_PATH"
    
    if [ -d ".venv" ]; then
      source .venv/bin/activate
    fi
    
    echo "Removed the problematic libXshm reference. Ready to try again!"
  '';
}