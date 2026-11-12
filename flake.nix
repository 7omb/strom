{
  description = "prerequisites for strom";

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
          python314FreeThreading
        ];

        jail = jail-nix.lib.init pkgs;
        claude-pkg = llm-agents.packages.${system}.claude-code;
        claudePkgs = with pkgs; [
          bashInteractive
          curl
          git
          gnumake
          gnused
          gawk
          gnutar
          gzip
          diffutils
          ripgrep
          jq
          findutils
          pre-commit
          uv
          ruff
          pyright
          ty
          nixpkgs-fmt
          which
          sqlite
          pythonEnv
          # The free-threaded build only as python3.14t:
          (pkgs.runCommand "python3.14t" { } ''
            mkdir -p $out/bin
            ln -s ${pkgs.python314FreeThreading}/bin/python3.14t $out/bin/
          '')
          # Single tools, not their collections: ps, pgrep and pkill of procps (leftover pytest and forkserver
          # workers), taskset of util-linux (a probe pinned to the fast cores):
          (pkgs.runCommand "process-tools" { } ''
            mkdir -p $out/bin
            ln -s ${pkgs.procps}/bin/ps ${pkgs.procps}/bin/pgrep ${pkgs.procps}/bin/pkill $out/bin/
            ln -s ${pkgs.util-linux}/bin/taskset $out/bin/
          '')
          # Profiles a command it starts (`py-spy record -- CMD`; ptrace reaches only its own children), and
          # times a short command over many runs (the hook command):
          py-spy
          hyperfine
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
            ruff
            ty
            nixpkgs-fmt
            uv
            direnv
            nix-direnv
            pre-commit
            entr
            gnumake
            py-spy
            hyperfine
            jailed-claude
          ] ++ pythonVersions;
          # Let uv use the python version of this flake by default:
          UV_PYTHON = pythonEnv.interpreter;
          # Each Python's setup hook exports its own sysconfigdata name; the last one (3.14t)
          # wins and breaks 3.14. Native interpreters find their own without these variables:
          shellHook = ''
            unset _PYTHON_SYSCONFIGDATA_NAME _PYTHON_HOST_PLATFORM
          '';
        };

        formatter = pkgs.nixpkgs-fmt;
      });
}
