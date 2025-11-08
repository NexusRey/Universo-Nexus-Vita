#!/bin/bash
set -ex
pip install pylint
mkdir -p test_dir
cd test_dir
git init
git ls-files '*.py' | xargs -r pylint
echo "Test passed"
