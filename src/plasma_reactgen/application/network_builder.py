from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from plasma_reactgen.application.channel_policy import (
    has_available_cross_section,
    is_channel_allowed,
    is_reaction_validation_allowed,
)
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
    ReactionChannel,
    ReactionNetwork,
    Species,
    SpeciesAmount,
    TruncationEvent,
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
        input_species_count = len(set(config.gases))
        if input_species_count > config.limits.max_species:
            raise ValueError(
                "limits.max_species must accommodate all unique input gases "
                f"({config.limits.max_species} < {input_species_count})"
            )

        reaction_catalog = self.deps.rule_repo.get_reaction_type_catalog()
        asset_exists = self._find_asset_exists_predicate()

        known_species: dict[str, Species] = {"e": make_electron_species()}
        active_species: dict[str, Species] = {"e": known_species["e"]}
        species_nodes: dict[str, NetworkSpeciesNode] = {}
        missing_data: list[MissingDataItem] = []
        truncations: list[TruncationEvent] = []

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
                truncations.append(
                    TruncationEvent(
                        limit_name="max_pairs_per_depth",
                        scope="pair_selection",
                        limit_value=config.limits.max_pairs_per_depth,
                        depth=depth,
                        observed_count=len(pairs),
                        retained_count=config.limits.max_pairs_per_depth,
                        omitted_count=len(pairs) - config.limits.max_pairs_per_depth,
                    )
                )
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
                    self._record_missing_report_truncation(
                        truncations=truncations,
                        depth=depth,
                        observed_count=missing_pairs_count,
                        limit=config.limits.max_missing_pairs_per_depth,
                    )
                    continue

                eligible_channels = [
                    channel
                    for channel in channels
                    if is_channel_allowed(
                        channel,
                        config,
                        pair=pair,
                        species=known_species,
                        asset_exists=asset_exists,
                    )
                    and channel.id not in seen_reaction_ids
                ]
                if not eligible_channels:
                    coverage.append(
                        CoverageItem(
                            pair_key=pair.key,
                            pair_label=pair.label,
                            family=pair.family,
                            depth=depth,
                            status="filtered",
                            reason="Registered channels did not pass the data policy",
                            n_channels=0,
                        )
                    )
                    continue

                coverage.append(
                    CoverageItem(
                        pair_key=pair.key,
                        pair_label=pair.label,
                        family=pair.family,
                        depth=depth,
                        status="found",
                        n_channels=len(eligible_channels),
                    )
                )

                reactants = [SpeciesAmount(pair.projectile, 1.0), SpeciesAmount(pair.target, 1.0)]

                for channel in eligible_channels:
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
                    if not is_reaction_validation_allowed(validation, config):
                        continue

                    equation = format_equation(reactants=reactants, products=channel.products)
                    channel_rule = reaction_catalog.get(pair.family, {}).get(channel.type, {})
                    expands_species = bool(channel_rule.get("expands_species", True))

                    if len(reactions) >= config.limits.max_reactions:
                        truncations.append(
                            TruncationEvent(
                                limit_name="max_reactions",
                                scope="reactions",
                                limit_value=config.limits.max_reactions,
                                depth=depth,
                                observed_count=len(reactions) + 1,
                                retained_count=len(reactions),
                                omitted_count=None,
                                details={"first_omitted_reaction_id": channel.id},
                            )
                        )
                        return ReactionNetwork(
                            species=known_species,
                            species_nodes=species_nodes,
                            reactions=reactions,
                            coverage=coverage,
                            missing_data=missing_data,
                            truncations=truncations,
                        )

                    introduced: list[str] = []
                    if expands_species:
                        new_species_ids = self._new_product_species_ids(
                            products=channel.products,
                            known_species=known_species,
                            species_nodes=species_nodes,
                        )
                        if (
                            len(species_nodes) + len(new_species_ids)
                            > config.limits.max_species
                        ):
                            self._record_species_truncation(
                                truncations=truncations,
                                depth=depth,
                                limit=config.limits.max_species,
                                retained_count=len(species_nodes),
                                channel_id=channel.id,
                                blocked_species_ids=new_species_ids,
                            )
                            seen_reaction_ids.add(channel.id)
                            continue
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
                        data_status=self._build_data_status(
                            channel=channel,
                            family=pair.family,
                            asset_exists=asset_exists,
                        ),
                        threshold_eV=channel.threshold_eV,
                        deltaE_products_minus_reactants_eV=channel.deltaE_products_minus_reactants_eV,
                        dnt_class=channel.dnt_class,
                        data=channel.data,
                    )

                    reactions.append(generated)
                    seen_reaction_ids.add(channel.id)

            if not new_frontier:
                break
            frontier = new_frontier

        return ReactionNetwork(
            species=known_species,
            species_nodes=species_nodes,
            reactions=reactions,
            coverage=coverage,
            missing_data=missing_data,
            truncations=truncations,
        )

    def _find_asset_exists_predicate(self) -> Callable[[str | None], bool] | None:
        for repository in (
            self.deps.reaction_repo,
            self.deps.species_repo,
            self.deps.rule_repo,
        ):
            predicate = getattr(repository, "asset_exists", None)
            if callable(predicate):
                return predicate
        return None

    def _new_product_species_ids(
        self,
        products: list[SpeciesAmount],
        known_species: dict[str, Species],
        species_nodes: dict[str, NetworkSpeciesNode],
    ) -> list[str]:
        return list(
            dict.fromkeys(
                amount.species
                for amount in products
                if amount.species != "e"
                and amount.species in known_species
                and amount.species not in species_nodes
            )
        )

    def _record_missing_report_truncation(
        self,
        *,
        truncations: list[TruncationEvent],
        depth: int,
        observed_count: int,
        limit: int,
    ) -> None:
        if observed_count <= limit:
            return
        existing = next(
            (
                event
                for event in truncations
                if event.limit_name == "max_missing_pairs_per_depth"
                and event.depth == depth
            ),
            None,
        )
        if existing is None:
            truncations.append(
                TruncationEvent(
                    limit_name="max_missing_pairs_per_depth",
                    scope="coverage.missing_pairs",
                    limit_value=limit,
                    depth=depth,
                    observed_count=observed_count,
                    retained_count=limit,
                    omitted_count=observed_count - limit,
                )
            )
            return
        existing.observed_count = observed_count
        existing.omitted_count = observed_count - limit

    def _record_species_truncation(
        self,
        *,
        truncations: list[TruncationEvent],
        depth: int,
        limit: int,
        retained_count: int,
        channel_id: str,
        blocked_species_ids: list[str],
    ) -> None:
        truncations.append(
            TruncationEvent(
                limit_name="max_species",
                scope="species_expansion",
                limit_value=limit,
                depth=depth,
                observed_count=retained_count + len(blocked_species_ids),
                retained_count=retained_count,
                omitted_count=len(blocked_species_ids),
                details={
                    "blocked_reaction_ids": [channel_id],
                    "blocked_species_ids": list(blocked_species_ids),
                },
            )
        )

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

    def _build_data_status(
        self,
        channel: ReactionChannel,
        family: str,
        asset_exists: Callable[[str | None], bool] | None,
    ) -> dict[str, str]:
        out = {"reaction": channel.status}
        if family == "electron":
            cs = channel.data.get("cross_section")
            if not cs:
                out["cross_section"] = "missing"
            elif isinstance(cs, dict) and cs.get("path"):
                out["cross_section"] = (
                    "local_file_registered"
                    if has_available_cross_section(channel, asset_exists)
                    else "path_registered_but_missing"
                )
            else:
                out["cross_section"] = (
                    cs.get("status", "reference_only_needs_import")
                    if isinstance(cs, dict)
                    else "reference_only_needs_import"
                )
        elif family == "ion_neutral":
            out["dnt_class"] = (
                "inferred" if channel.status == "inferred" else "registered"
            )
        return out
