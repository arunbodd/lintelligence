#!/usr/bin/env python3
"""
Setup script for LIntelligence - a nextflow pipeline validator.
"""

from pathlib import Path
from setuptools import setup, find_packages

# Read the README file
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""

# Read requirements
requirements_file = Path(__file__).parent / "requirements.txt"
if requirements_file.exists():
    with open(requirements_file, 'r', encoding='utf-8') as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]
else:
    requirements = [
        "click>=8.0.0",
        "pydantic>=2.0.0",
        "pyyaml>=6.0",
        "jinja2>=3.0.0",
        "colorama>=0.4.0",
        "tabulate>=0.9.0",
        "aiofiles>=23.0.0",
        "ply>=3.11",
    ]

# Optional dependencies
extras_require = {
    "excel": ["pandas>=1.5.0", "openpyxl>=3.0.0"],
    "dev": [
        "pytest>=7.0.0",
        "pytest-asyncio>=0.21.0",
        "pytest-cov>=4.0.0",
        "black>=23.0.0",
        "flake8>=6.0.0",
        "mypy>=1.0.0",
        "pre-commit>=3.0.0",
    ],
    "docs": [
        "sphinx>=6.0.0",
        "sphinx-rtd-theme>=1.2.0",
        "myst-parser>=1.0.0",
    ],
}

# All optional dependencies
extras_require["all"] = sum(extras_require.values(), [])

setup(
    name="lintelligence",
    version="1.0.0",
    author="Arun Boddapati",
    author_email="arunbodd@outlook.com",
    description="Comprehensive validation tool for Nextflow pipelines against ph-core and AMDP guidelines",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/arunbodd/lintelligence",
    project_urls={
        "Bug Reports": "https://github.com/arunbodd/lintelligence/issues",
        "Source": "https://github.com/arunbodd/lintelligence",
        "Documentation": "https://arunbodd.github.io/lintelligence/",
    },
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={
        "lintelligence": [
            "rules/*.yml",
            "rules/*.yaml",
            "rules/*.json",
            "reporting/templates/*.html",
            "reporting/templates/*.css",
            "reporting/templates/*.js",
        ],
    },
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=requirements,
    extras_require=extras_require,
    entry_points={
        "console_scripts": [
            "lintelligence=smart_validator:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
        "Topic :: Software Development :: Quality Assurance",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    keywords=[
        "nextflow",
        "pipeline",
        "validation",
        "bioinformatics",
        "ph-core",
        "amdp",
        "compliance",
        "quality-assurance",
    ],
    zip_safe=False,
)
