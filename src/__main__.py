import sys

from .cli import main as cli_main


def main():
    """Entry point supporting both CLI and GUI modes."""
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        # Remove --gui from args and launch GUI
        sys.argv.pop(1)
        from .gui import main as gui_main
        gui_main()
    else:
        cli_main()


if __name__ == "__main__":
    main()
