"""Registry-driven reaction-network and dataset generator for low-pressure plasma.

Input gases and process conditions in, a reviewed reaction list plus the
numerical datasets a plasma model needs out. Reading order::

    model      value types
    registry   load the local YAML registry
    case       gases and process conditions
    expand     grow the network from the input gases
    balance    conservation checks
    physics    quantities derived from registered values
    audit      what is missing or inconsistent
    export     write the output bundle
    lock       pin the data a run used
    plan       route gaps to acquisition sources
    cli        the three commands
"""

__version__ = "0.2.0"
