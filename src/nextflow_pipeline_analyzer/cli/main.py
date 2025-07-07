#!/usr/bin/env python3
"""
Main CLI entry point for nextflow-pipeline-analyzer.
"""

import sys
import os
from pathlib import Path

def app():
    """Entry point for nf-analyze command."""
    # This is just a placeholder for the entry point defined in pyproject.toml
    pass

def cli():
    """Entry point for nextflow-analyzer and nf-analyzer commands."""
    # This is just a placeholder for the entry points defined in setup.py
    pass

def main():
    """Entry point for the lintelligence command."""
    # Get the root directory of the project
    root_dir = Path(__file__).parent.parent.parent.parent
    
    # Path to the original smart_validator.py script
    smart_validator_path = root_dir / "smart_validator.py"
    
    if not smart_validator_path.exists():
        print(f"Error: Could not find {smart_validator_path}")
        sys.exit(1)
    
    # Execute the script with the same arguments
    sys.path.insert(0, str(root_dir))
    from smart_validator import main as smart_validator_main
    
    # Call the main function from smart_validator.py
    smart_validator_main()

if __name__ == "__main__":
    main()
