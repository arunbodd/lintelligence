#!/bin/bash
# Simple wrapper to run the smart_validator.py script directly

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Run the Python script with all arguments passed to this script
python "$DIR/smart_validator.py" "$@"
