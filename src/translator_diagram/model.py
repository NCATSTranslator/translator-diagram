"""The parsed shape of one row of the components sheet."""

from dataclasses import dataclass, field


@dataclass
class Component:
    """A single row of the components CSV after parsing."""

    id: str
    name: str
    owner: str
    itrb: str
    refactor_status: str
    notes: str
    url: str = ""
    ubiquitous: bool = False
    hide: bool = False
    part_of: str = ""
    hosted_at: str = ""
    layer: str = ""
    externals: list[tuple[str, str]] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    depends_on_planned: list[str] = field(default_factory=list)
    uses: list[str] = field(default_factory=list)
    uses_planned: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        # Fall back to id when Name is missing — otherwise the label
        # starts with a blank line.
        return self.name or self.id

    def all_refs(self) -> list[str]:
        return (
            self.depends_on
            + self.depends_on_planned
            + self.uses
            + self.uses_planned
        )


def index_by_id(components: list[Component]) -> dict[str, Component]:
    """Case-insensitive lookup from lower(id) to Component."""
    return {c.id.lower(): c for c in components}
