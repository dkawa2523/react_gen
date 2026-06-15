# Electron cross-section assets

This registry update stores physically grounded reaction channels, thresholds, and provenance, but does not embed numeric electron-collision cross-section curves.

Import numerical curves later from LXCat/Bordage/Phelps/NIST sources using a dedicated importer, then set `data.cross_section.path` in the relevant reaction YAML files.
