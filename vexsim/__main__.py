from vexsim.cli import main

# Guarded: benchmark worker processes re-import this module on Windows (spawn).
if __name__ == "__main__":
    raise SystemExit(main())
