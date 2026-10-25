{
  description = "prerequisites for pipes";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    jail-nix.url = "sourcehut:~alexdavid/jail.nix";
    llm-agents.url = "github:numtide/llm-agents.nix";
  };

  outputs = { self, nixpkgs, flake-utils, jail-nix, llm-agents }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        pythonEnv = pkgs.python314;
        pythonVersions = with pkgs; [
          pythonEnv
          python313
          python312
        ];

        jail = jail-nix.lib.init pkgs;
        claude-pkg = llm-agents.packages.${system}.claude-code;
        claudePkgs = with pkgs; [
          bashInteractive
          curl
          git
          gnused
          ripgrep
          jq
          findutils
          jetbrains.jdk
          kotlin
          ktfmt
          detekt
          deno
          pre-commit
        ];
        jailed-claude = jail "jailed-claude" claude-pkg (with jail.combinators; [
          network
          time-zone
          no-new-session
          mount-cwd
          (readwrite (noescape "~/.claude.json"))
          (readwrite (noescape "~/.claude"))
          (readwrite (noescape "~/.config/claude"))
          (readwrite (noescape "~/.local/share/claude"))
          (add-pkg-deps claudePkgs)
        ]);
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            pyright
            uv
            direnv
            nix-direnv
            pre-commit
            entr
            gnumake
            jailed-claude
          ] ++ pythonVersions;
          # Use nix-ld when on NixOS, because ruff depends on libc:
          NIX_LD_LIBRARY_PATH = with pkgs; lib.makeLibraryPath [
            stdenv.cc.cc
          ];
          # Let uv use the python version of this flake by default:
          UV_PYTHON = pythonEnv.interpreter;
        };

        apps.tox = flake-utils.lib.mkApp {
          drv = pkgs.writeShellApplication {
            name = "run-tox";
            runtimeInputs = with pkgs; [
              uv
            ] ++ pythonVersions;
            text = ''
              uv run tox
            '';
          };
        };

        apps.build = flake-utils.lib.mkApp {
          drv = pkgs.writeShellApplication {
            name = "build";
            runtimeInputs = with pkgs; [
              uv
              pythonEnv
            ];
            text = ''
              uv build
            '';
          };
        };

        formatter = pkgs.nixpkgs-fmt;
      });
}
