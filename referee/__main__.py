"""`python -m referee ...` -> the Referee CLI (certify / verify)."""
from referee.cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
