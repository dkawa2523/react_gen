from __future__ import annotations

from dataclasses import dataclass

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.pair_selection import select_pairs_involving_frontier
from plasma_reactgen.application.ports import ReactionRepository, RuleRepository, SpeciesRepository
from plasma_reactgen.domain.chemistry import is_excited_state, make_electron_species, species_has_any_class
from plasma_reactgen.domain.equations import format_equation
from plasma_reactgen.domain.models import (
    CollisionPair,
    CoverageItem,
    GeneratedReaction,
    MissingDataItem,
    NetworkSpeciesNode,
    ReactionNetwork,
    Species,
    SpeciesAmount,
)
from plasma_reactgen.validation.validators import validate_reaction


@dataclass
class NetworkBuilderDependencies:
    species_repo: SpeciesRepository
    reaction_repo: ReactionRepository
    rule_repo: RuleRepository


class ReactionNetworkBuilder:
    """Build a reaction network from registered species and pair-channel data.

    The builder is intentionally permissive: missing cross-section data and DNT
    properties are reported by diagnostics instead of blocking network generation.
    Charge/element balance failures are rejected because they indicate malformed
    registered channels.
    """

    def __init__(self, deps: NetworkBuilderDependencies):
        self.deps = deps

    def generate(self, config: CaseConfig) -> ReactionNetwork:
        reaction_catalog = self.deps.rule_repo.get_reaction_type_catalog()

        known_species: dict[str, Species] = {"e": make_electron_species()}
        active_species: dict[str, Species] = {"e": known_species["e"]}
        species_nodes: dict[str, NetworkSpeciesNode] = {}
        missing_data: list[MissingDataItem] = []

        for gas in config.gases:
            sp = self.deps.species_repo.get_species(gas)
            if sp is None:
                raise ValueError(f"Input gas species is not registered: {gas}")
            known_species[gas] = sp
            active_species[gas] = sp
            species_nodes[gas] = NetworkSpeciesNode(
                species_id=gas,
                depth_first_seen=0,
                introduced_by=["input_gas"],
                roles={"input_gas"},
                propagated=True,
            )

        frontier = set(config.gases)
        reactions: list[GeneratedReaction] = []
        coverage: list[CoverageItem] = []
        seen_reaction_ids: set[str] = set()
        seen_pair_keys: set[str] = set()

        for depth in range(config.expansion.max_depth + 1):
            pairs = select_pairs_involving_frontier(active_species, frontier, config)
            if len(pairs) > config.limits.max_pairs_per_depth:
                pairs = pairs[: config.limits.max_pairs_per_depth]

            new_frontier: set[str] = set()
            missing_pairs_count = 0

            for pair in pairs:
                if pair.key in seen_pair_keys:
                    continue
                seen_pair_keys.add(pair.key)

                channels = self.deps.reaction_repo.get_channels(pair)
                if not channels:
                    if missing_pairs_count < config.limits.max_missing_pairs_per_depth:
                        coverage.append(
                            CoverageItem(
                                pair_key=pair.key,
                                pair_label=pair.label,
                                family=pair.family,
                                depth=depth,
                                status="missing",
                                reason="No registered reaction file",
                                n_channels=0,
                            )
                        )
                    missing_pairs_count += 1
                    continue

                coverage.append(
                    CoverageItem(
                        pair_key=pair.key,
                        pair_label=pair.label,
                        family=pair.family,
                        depth=depth,
                        status="found",
                        n_channels=len(channels),
                    )
                )

                reactants = [SpeciesAmount(pair.projectile, 1.0), SpeciesAmount(pair.target, 1.0)]

                for channel in channels:
                    if channel.status in config.data_policy.exclude_status:
                        continue
                    if channel.status not in config.data_policy.allowed_status:
                        continue
                    if channel.id in seen_reaction_ids:
                        continue

                    self._load_registered_product_species(
                        products=channel.products,
                        known_species=known_species,
                        missing_data=missing_data,
                        channel_id=channel.id,
                    )

                    validation = validate_reaction(
                        reactants=reactants,
                        products=channel.products,
                        species=known_species,
                    )

                    if validation["charge_balance"] == "failed" or validation["element_balance"] == "failed":
                        missing_data.append(
                            MissingDataItem(
                                subject_kind="reaction",
                                subject_id=channel.id,
                                field="validation",
                                required_by="network_builder",
                                severity="error",
                                message=(
                                    "Reaction rejected because charge or element "
                                    "balance failed."
                                ),
                            )
                        )
                        continue

                    equation = format_equation(reactants=reactants, products=channel.products)
                    channel_rule = reaction_catalog.get(pair.family, {}).get(channel.type, {})
                    expands_species = bool(channel_rule.get("expands_species", True))

                    introduced: list[str] = []
                    if expands_species:
                        introduced = self._register_product_nodes(
                            channel_id=channel.id,
                            depth=depth,
                            products=channel.products,
                            known_species=known_species,
                            active_species=active_species,
                            species_nodes=species_nodes,
                            new_frontier=new_frontier,
                            config=config,
                            missing_data=missing_data,
                        )

                    generated = GeneratedReaction(
                        id=channel.id,
                        depth=depth,
                        family=pair.family,
                        type=channel.type,
                        equation=equation,
                        reactants=reactants,
                        products=channel.products,
                        source_pair_key=pair.key,
                        source_pair_label=pair.label,
                        introduced_species=introduced,
                        validation=validation,
                        data_status=self._build_data_status(channel_data=channel.data, family=pair.family, status=channel.status),
                        threshold_eV=channel.threshold_eV,
                        deltaE_products_minus_reactants_eV=channel.deltaE_products_minus_reactants_eV,
                        dnt_class=channel.dnt_class,
                        data=channel.data,
                    )

                    reactions.append(generated)
                    seen_reaction_ids.add(channel.id)

                    if len(reactions) >= config.limits.max_reactions:
                        return ReactionNetwork(known_species, species_nodes, reactions, coverage, missing_data)

            if not new_frontier:
                break
            frontier = new_frontier

            if len(species_nodes) >= config.limits.max_species:
                break

        return ReactionNetwork(known_species, species_nodes, reactions, coverage, missing_data)

    def _load_registered_product_species(
        self,
        products: list[SpeciesAmount],
        known_species: dict[str, Species],
        missing_data: list[MissingDataItem],
        channel_id: str,
    ) -> None:
        for amount in products:
            sid = amount.species
            if sid == "e" or sid in known_species:
                continue
            sp = self.deps.species_repo.get_species(sid)
            if sp is None:
                missing_data.append(
                    MissingDataItem(
                        subject_kind="species",
                        subject_id=sid,
                        field="registry/species",
                        required_by=channel_id,
                        severity="required",
                        message="Product species is referenced by a reaction but not registered.",
                    )
                )
                continue
            known_species[sid] = sp

    def _register_product_nodes(
        self,
        channel_id: str,
        depth: int,
        products: list[SpeciesAmount],
        known_species: dict[str, Species],
        active_species: dict[str, Species],
        species_nodes: dict[str, NetworkSpeciesNode],
        new_frontier: set[str],
        config: CaseConfig,
        missing_data: list[MissingDataItem],
    ) -> list[str]:
        introduced: list[str] = []

        for amount in products:
            sid = amount.species
            if sid == "e":
                continue
            if sid not in known_species:
                continue

            first_seen = sid not in species_nodes
            if first_seen:
                species_nodes[sid] = NetworkSpeciesNode(
                    species_id=sid,
                    depth_first_seen=depth + 1,
                    introduced_by=[channel_id],
                    roles={"reaction_product"},
                    propagated=False,
                )
                introduced.append(sid)
            else:
                if channel_id not in species_nodes[sid].introduced_by:
                    species_nodes[sid].introduced_by.append(channel_id)
                species_nodes[sid].roles.add("reaction_product")

            if first_seen and self._should_propagate_species(known_species[sid], config):
                active_species[sid] = known_species[sid]
                species_nodes[sid].propagated = True
                new_frontier.add(sid)

        return introduced

    def _should_propagate_species(self, species: Species, config: CaseConfig) -> bool:
        if not species_has_any_class(species, config.expansion.propagate_species_classes):
            return False
        if is_excited_state(species) and not config.expansion.propagate_excited_states:
            return False
        return True

    def _build_data_status(self, channel_data: dict, family: str, status: str) -> dict[str, str]:
        out = {"reaction": status}
        if family == "electron":
            cs = channel_data.get("cross_section")
            if not cs:
                out["cross_section"] = "missing"
            elif cs.get("path"):
                out["cross_section"] = "local_file_registered"
            else:
                out["cross_section"] = cs.get("status", "reference_only_needs_import")
        elif family == "ion_neutral":
            out["dnt_class"] = "registered"
        return out
