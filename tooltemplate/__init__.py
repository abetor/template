"""Deterministic tool-repository generator and regeneration drift detector.

Run it with ``python3 -m tooltemplate {birth,diff}``. The runtime uses only the Python
standard library. Birth determinism ensures temporary and target stamping cancel byte for
byte, preserving the meaning of drift reports.
"""
