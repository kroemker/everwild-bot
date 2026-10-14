"""Entry point: ``python -m everwild <command>``."""

import sys


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    if command == "play":
        from .play_local import main as play

        play(sys.argv[2:])
    else:
        print("Befehle:\n  play   Everwild lokal im Terminal spielen (python -m everwild play --help)")


if __name__ == "__main__":
    main()
