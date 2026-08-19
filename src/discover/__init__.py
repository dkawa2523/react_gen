"""Propose reaction channels a species could have, and route them to a source.

Optional and independent: nothing in ``reactgen`` or ``acquire`` imports this
package, and every channel it writes carries ``status: candidate``, which no
case accepts by default.

    fragments   enumerate channels from the formula, under conservation
    relations   which species is the ion, anion or ground state of which
    propose     answer for species the registry does not cover
    screen      which ion-neutral and neutral channels are open by energy
    view        the registry projections discovery needs
    sources     which database covers what, and whether it is reachable now
    evidence    ask the reachable sources whether a candidate is real
    cli         the two commands
"""

__version__ = "0.1.0"
