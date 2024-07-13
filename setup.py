#!/usr/bin/env python

"""The setup script."""

from setuptools import setup, find_packages

with open("README.md") as readme_file:
    readme = readme_file.read()

requirements = [
    "Click>=7.0",
    "rich",
    "loguru",
]

test_requirements = ["pytest>=3", "pytest-order"]

setup(
    author="Hendrik Klug",
    author_email="hendrik.klug@gmail.com",
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.11",
    ],
    description="Chain pull requests from your devbranch's commits.",
    entry_points={
        "console_scripts": [
            "ghchain=ghchain.cli:ghchain_cli",
        ],
    },
    install_requires=requirements,
    license="MIT license",
    long_description=readme,
    long_description_content_type="text/markdown",
    include_package_data=True,
    keywords="ghchain",
    name="ghchain",
    packages=find_packages(include=["ghchain", "ghchain.*"]),
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/Jimmy2027/ghchain",
    version="0.1.0",
    zip_safe=False,
)
