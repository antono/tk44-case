{
  description = "3D-printable tray case and wrist rests for the Ladniy/TK44 keyboard (FreeCAD)";

  # Pinned to a revision whose FreeCAD (1.1.1) is in the binary cache and
  # known to build this model. Bump with `nix flake update`, then re-test.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/d233902339c02a9c334e7e593de68855ad26c4cb";

  outputs =
    { self, nixpkgs }:
    let
      # FreeCAD in nixpkgs is Linux-only
      forAllSystems = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
      ];
    in
    {
      # `nix run` (from the repo root) rebuilds the model: STEP/STL into out/
      # and the tracked tk44-case.FCStd next to the script.
      apps = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          build = pkgs.writeShellApplication {
            name = "tk44-case";
            runtimeInputs = [ pkgs.freecad ];
            text = ''
              if [ ! -f tk44_case.py ]; then
                echo "run from the tk44-case repo root" >&2
                exit 1
              fi
              freecad -c tk44_case.py </dev/null
            '';
          };
        in
        {
          default = {
            type = "app";
            program = "${build}/bin/tk44-case";
          };
        }
      );

      devShells = forAllSystems (system: {
        default = nixpkgs.legacyPackages.${system}.mkShell {
          packages = with nixpkgs.legacyPackages.${system}; [
            freecad
            python3
          ];
        };
      });
    };
}
