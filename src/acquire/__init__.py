"""Turn acquired files into snapshots that `rgen ingest` can read.

Separate from ``reactgen`` on purpose: this package may open a network
connection and parse foreign formats, and the generator may do neither.

    lxcat      parse an LXCat export into per-process cross sections
    atoms      read atomic ionization energy and electron affinity
    ideal_gas  read formation enthalpy from the NASA Glenn tables
    chemkin    parse a CHEMKIN thermodynamic file into NASA polynomials
    umist      parse a UMIST RATE release into rate records
    pubchem    fetch and verify species identity
    snapshot   write the snapshot and its table assets
    cli        the commands
"""

__version__ = "0.1.0"
