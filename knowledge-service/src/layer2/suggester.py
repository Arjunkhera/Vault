"""
Metadata suggestion engine for Knowledge Service write path.

Given page content (and optional hints), analyses the text, searches existing
registries and the knowledge base (via SearchStore), and returns per-field
suggestions with confidence levels and reasons.

Degrades gracefully on cold start (empty registries / empty KB).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from ..layer1.interface import SearchStore
from .frontmatter import parse_page
from .schema import SchemaLoader, _build_alias_map, _fuzzy_match_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Suggestion result models
# ---------------------------------------------------------------------------

CONFIDENCE_LEVELS = ("high", "medium", "low", "none")


@dataclass
class FieldSuggestion:
    """Suggestion for a single frontmatter field."""
    value: Optional[str | list] = None
    confidence: str = "none"
    reason: str = ""
    alternatives: list[dict] = field(default_factory=list)
    unmatched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {"value": self.value, "confidence": self.confidence, "reason": self.reason}
        if self.alternatives:
            d["alternatives"] = self.alternatives
        if self.unmatched_keywords:
            d["unmatched_keywords"] = self.unmatched_keywords
        return d


@dataclass
class ScopeSuggestions:
    """Nested suggestions for the scope object."""
    company: Optional[FieldSuggestion] = None
    org: Optional[FieldSuggestion] = None
    squad: Optional[FieldSuggestion] = None
    service: Optional[FieldSuggestion] = None
    repo: Optional[FieldSuggestion] = None

    def to_dict(self) -> dict:
        d: dict = {}
        for name in ("company", "org", "squad", "service", "repo"):
            val = getattr(self, name)
            if val is not None:
                d[name] = val.to_dict()
        return d


@dataclass
class SuggestionResult:
    """Aggregate suggestions for all frontmatter fields."""
    kb_status: str = "populated"  # "populated" | "sparse" | "empty"
    suggestions: dict[str, FieldSuggestion | ScopeSuggestions] = field(default_factory=dict)

    def to_dict(self) -> dict:
        out: dict = {"kb_status": self.kb_status, "suggestions": {}}
        for key, val in self.suggestions.items():
            if isinstance(val, ScopeSuggestions):
                out["suggestions"][key] = val.to_dict()
            else:
                out["suggestions"][key] = val.to_dict()
        return out


# ---------------------------------------------------------------------------
# Content analysis helpers
# ---------------------------------------------------------------------------

_TYPE_SIGNALS: list[tuple[str, list[str]]] = [
    ("procedure", ["step 1", "step 2", "step-by-step", "steps to", "how to run", "## steps"]),
    ("guide", ["getting started", "setup", "installation", "install", "prerequisites", "configure", "how to"]),
    ("learning", ["post-mortem", "postmortem", "incident", "root cause", "rca", "lesson", "edge case"]),
    ("keystone", ["navigation", "hub", "starting point", "index of", "## overview", "## what is"]),
    ("service-overview", ["service overview", "what it does", "api endpoints", "tech stack", "deployment"]),
    ("repo-profile", ["repository", "build command", "tech stack", "module structure", "## modules"]),
    ("team-conventions", ["convention", "team standard", "ways of working", "code style", "review process"]),
    ("concept", ["architecture", "design", "pattern", "model", "domain", "how it works"]),
]

_MODE_SIGNALS: dict[str, list[str]] = {
    "operational": ["workflow", "runbook", "on-call", "playbook", "team process", "sprint", "standup"],
    "keystone": ["navigation hub", "starting point", "index", "overview hub"],
}


def _classify_type(body: str) -> tuple[str, str, list[dict]]:
    """
    Classify page type from body text.

    Returns (best_type, reason, alternatives).
    """
    lower = body.lower()
    scores: dict[str, int] = {}
    for type_id, signals in _TYPE_SIGNALS:
        count = sum(1 for s in signals if s in lower)
        if count:
            scores[type_id] = count

    if not scores:
        return "concept", "No strong type signals in content; defaulting to concept", []

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best, best_count = ranked[0]
    alts = [{"value": t, "reason": f"Matched {c} signal(s)"} for t, c in ranked[1:3]]
    return best, f"Matched {best_count} signal(s) for type '{best}'", alts


def _classify_mode(body: str, page_type: Optional[str], allowed_modes: list[str]) -> tuple[str, str]:
    """
    Classify mode from body text, constrained to allowed_modes if provided.
    """
    lower = body.lower()

    for mode, signals in _MODE_SIGNALS.items():
        if any(s in lower for s in signals):
            if not allowed_modes or mode in allowed_modes:
                return mode, f"Content contains {mode} signals"

    if page_type == "keystone":
        return "keystone", "Keystone page type defaults to keystone mode"

    default = "reference"
    if allowed_modes and default not in allowed_modes:
        default = allowed_modes[0]
    return default, "Default mode for general knowledge content"


def _generate_description(body: str) -> tuple[str, str]:
    """
    Generate a ~150-char description from the first substantive paragraph.
    """
    lines = body.strip().split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("```"):
            continue
        if stripped.startswith("|"):
            continue
        if stripped.startswith("-") or stripped.startswith("*"):
            continue
        # Found a prose line
        if len(stripped) <= 200:
            return stripped, "Extracted from first content paragraph"
        return stripped[:197] + "...", "Truncated from first content paragraph"

    return "", "No suitable paragraph found for description"


def _extract_keywords(body: str, min_length: int = 3) -> list[str]:
    """Extract candidate keywords from body text (simple word-frequency approach)."""
    stop_words = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "her",
        "was", "one", "our", "out", "has", "its", "with", "this", "that", "from",
        "they", "been", "have", "will", "each", "make", "when", "what", "there",
        "into", "also", "more", "than", "them", "some", "very", "after", "should",
        "about", "which", "these", "other", "their", "would", "could",
    }
    words = re.findall(r"[a-z][a-z0-9-]+", body.lower())
    freq: dict[str, int] = {}
    for w in words:
        if len(w) >= min_length and w not in stop_words:
            freq[w] = freq.get(w, 0) + 1

    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in ranked[:30]]


def _extract_repo_mentions(body: str) -> list[str]:
    """Extract plausible repo names from URLs and code references."""
    repos: list[str] = []
    # GitHub URLs: github.com/org/repo or github.intuit.com/org/repo
    for m in re.finditer(r"github(?:\.intuit)?\.com/[\w-]+/([\w.-]+)", body):
        repos.append(m.group(1))
    # Backtick-quoted repo-like names (kebab-case, >=2 parts)
    for m in re.finditer(r"`([\w]+-[\w-]+)`", body):
        candidate = m.group(1)
        if not candidate.startswith("--") and len(candidate) <= 50:
            repos.append(candidate)
    return list(dict.fromkeys(repos))  # dedupe, preserve order


# ---------------------------------------------------------------------------
# KB status detection
# ---------------------------------------------------------------------------

def _detect_kb_status(store: Optional[SearchStore]) -> str:
    """Probe the KB to determine populated / sparse / empty."""
    if store is None:
        return "empty"
    try:
        paths = store.list_documents()
        if not paths:
            return "empty"
        if len(paths) < 5:
            return "sparse"
        return "populated"
    except Exception:
        return "empty"


# ---------------------------------------------------------------------------
# Main suggester
# ---------------------------------------------------------------------------

class MetadataSuggester:
    """
    Suggests frontmatter metadata for a knowledge page.

    Usage:
        suggester = MetadataSuggester(schema_loader, store=search_store)
        result = suggester.suggest(content, hints={"scope.service": "Document Service"})
    """

    def __init__(self, loader: SchemaLoader, store: Optional[SearchStore] = None):
        self._loader = loader
        self._store = store

    def suggest(self, content: str, hints: Optional[dict] = None) -> SuggestionResult:
        """
        Analyse page content and return per-field suggestions.

        Args:
            content: Full markdown with optional partial frontmatter.
            hints:   Optional dict of known values (e.g. {"scope.service": "Document Service"}).
        """
        hints = hints or {}

        # Parse existing frontmatter (may be partial/empty)
        try:
            parsed = parse_page(content)
            body = parsed.body
        except Exception:
            body = content

        kb_status = _detect_kb_status(self._store)
        result = SuggestionResult(kb_status=kb_status)

        # --- type ---
        result.suggestions["type"] = self._suggest_type(body, hints)

        # Resolve type for downstream use
        type_val = (
            hints.get("type")
            or (result.suggestions["type"].value if isinstance(result.suggestions["type"], FieldSuggestion) else None)
        )
        pt = self._loader.get_page_type(type_val) if type_val else None
        allowed_modes = pt.allowed_modes if pt else []

        # --- mode ---
        result.suggestions["mode"] = self._suggest_mode(body, type_val, allowed_modes, hints)

        # --- description ---
        result.suggestions["description"] = self._suggest_description(body, hints)

        # --- tags ---
        result.suggestions["tags"] = self._suggest_tags(body, kb_status, hints)

        # --- scope ---
        result.suggestions["scope"] = self._suggest_scope(body, kb_status, hints)

        # --- related ---
        result.suggestions["related"] = self._suggest_related(body, kb_status, hints)

        # --- owner ---
        result.suggestions["owner"] = self._suggest_owner(body, kb_status, hints)

        # --- dependency / consumer / applies-to (lightweight) ---
        for dep_field in ("depends-on", "consumed-by", "applies-to"):
            result.suggestions[dep_field] = FieldSuggestion(
                value=[],
                confidence="low",
                reason=f"Automatic {dep_field} detection not yet implemented",
            )

        return result

    # -- per-field strategies ------------------------------------------------

    def _suggest_type(self, body: str, hints: dict) -> FieldSuggestion:
        if "type" in hints:
            pt = self._loader.get_page_type(hints["type"])
            if pt:
                return FieldSuggestion(
                    value=hints["type"], confidence="high", reason="From hint"
                )

        best, reason, alts = _classify_type(body)
        return FieldSuggestion(
            value=best,
            confidence="medium",
            reason=reason,
            alternatives=alts,
        )

    def _suggest_mode(
        self, body: str, page_type: Optional[str], allowed_modes: list[str], hints: dict,
    ) -> FieldSuggestion:
        if "mode" in hints:
            if not allowed_modes or hints["mode"] in allowed_modes:
                return FieldSuggestion(
                    value=hints["mode"], confidence="high", reason="From hint"
                )

        mode, reason = _classify_mode(body, page_type, allowed_modes)
        return FieldSuggestion(value=mode, confidence="medium", reason=reason)

    def _suggest_description(self, body: str, hints: dict) -> FieldSuggestion:
        if "description" in hints:
            return FieldSuggestion(
                value=hints["description"], confidence="high", reason="From hint"
            )

        desc, reason = _generate_description(body)
        conf = "medium" if desc else "none"
        return FieldSuggestion(value=desc or None, confidence=conf, reason=reason)

    def _suggest_tags(self, body: str, kb_status: str, hints: dict) -> FieldSuggestion:
        keywords = _extract_keywords(body)
        tag_entries = self._loader.get_registry("tags")

        if not tag_entries:
            return FieldSuggestion(
                value=[],
                confidence="none",
                reason="Tags registry is empty — extracted keywords listed as candidates",
                unmatched_keywords=keywords[:15],
            )

        alias_map = _build_alias_map(tag_entries)
        matched: list[str] = []
        unmatched: list[str] = []

        for kw in keywords:
            canonical, _ = _fuzzy_match_registry(kw, tag_entries, cutoff=0.75)
            if canonical and canonical not in matched:
                matched.append(canonical)
            elif canonical is None and kw not in unmatched:
                unmatched.append(kw)

        # Also check tags of similar pages via KB search
        if self._store and kb_status == "populated" and body:
            try:
                search_results = self._store.hybrid_search(body[:300], limit=5)
                for sr in search_results:
                    doc_content = self._store.get_document(sr.file_path)
                    if doc_content:
                        neighbour = parse_page(doc_content)
                        for t in neighbour.tags:
                            if t not in matched:
                                matched.append(t)
            except Exception as e:
                logger.debug("Tag suggestion KB search failed: %s", e)

        conf = "medium" if matched else "none"
        reason = "Extracted from content keywords, matched against tags registry"
        if kb_status != "populated":
            reason += f" (KB status: {kb_status})"
        if unmatched:
            reason += f". {len(unmatched)} keyword(s) not in registry"

        return FieldSuggestion(
            value=matched[:15],
            confidence=conf,
            reason=reason,
            unmatched_keywords=unmatched[:10],
        )

    def _suggest_scope(self, body: str, kb_status: str, hints: dict) -> ScopeSuggestions:
        scope = ScopeSuggestions()

        # --- service (from hint or content mention) ---
        svc_entries = self._loader.get_registry("services")
        svc_value: Optional[str] = None

        if hints.get("scope.service"):
            svc_value = hints["scope.service"]
            scope.service = FieldSuggestion(
                value=svc_value, confidence="high", reason="From hint"
            )
        elif svc_entries:
            alias_map = _build_alias_map(svc_entries)
            lower_body = body.lower()
            for entry in svc_entries:
                names_to_check = [entry.id] + entry.aliases
                for name in names_to_check:
                    if name.lower() in lower_body:
                        svc_value = entry.id
                        scope.service = FieldSuggestion(
                            value=entry.id,
                            confidence="medium",
                            reason=f"Content mentions '{name}'",
                        )
                        break
                if svc_value:
                    break

        if scope.service is None:
            scope.service = FieldSuggestion(
                value=None,
                confidence="none",
                reason="No service mention found in content"
                + (" (services registry is empty)" if not svc_entries else ""),
            )

        # --- org (derived from service → org mapping) ---
        if svc_value and svc_entries:
            for entry in svc_entries:
                if entry.id == svc_value and entry.scope_org:
                    scope.org = FieldSuggestion(
                        value=entry.scope_org,
                        confidence="high",
                        reason=f"Derived from service '{svc_value}' → org mapping",
                    )
                    break

        if scope.org is None:
            if hints.get("scope.org"):
                scope.org = FieldSuggestion(
                    value=hints["scope.org"], confidence="high", reason="From hint"
                )
            else:
                org_entries = self._loader.get_registry("orgs")
                scope.org = FieldSuggestion(
                    value=None, confidence="none",
                    reason="No org info found"
                    + (" (orgs registry is empty)" if not org_entries else ""),
                )

        # --- squad ---
        team_entries = self._loader.get_registry("teams")
        if hints.get("scope.squad"):
            scope.squad = FieldSuggestion(
                value=hints["scope.squad"], confidence="high", reason="From hint"
            )
        elif team_entries:
            lower_body = body.lower()
            for entry in team_entries:
                names_to_check = [entry.id] + entry.aliases
                for name in names_to_check:
                    if name.lower() in lower_body:
                        scope.squad = FieldSuggestion(
                            value=entry.id, confidence="medium",
                            reason=f"Content mentions '{name}'",
                        )
                        break
                if scope.squad is not None:
                    break

        if scope.squad is None:
            scope.squad = FieldSuggestion(
                value=None, confidence="none",
                reason="No squad info found in content"
                + (" (teams registry is empty)" if not team_entries else ""),
            )

        # --- repo ---
        repo_mentions = _extract_repo_mentions(body)
        if hints.get("scope.repo"):
            scope.repo = FieldSuggestion(
                value=hints["scope.repo"], confidence="high", reason="From hint"
            )
        elif repo_mentions:
            scope.repo = FieldSuggestion(
                value=repo_mentions[0],
                confidence="medium",
                reason=f"Found repo reference in content",
                alternatives=[{"value": r, "reason": "Also mentioned"} for r in repo_mentions[1:3]],
            )
        else:
            scope.repo = FieldSuggestion(
                value=None, confidence="none", reason="No repo references found in content"
            )

        return scope

    def _suggest_related(self, body: str, kb_status: str, hints: dict) -> FieldSuggestion:
        if kb_status == "empty":
            return FieldSuggestion(
                value=[], confidence="none",
                reason="KB is empty — no pages to match against",
            )

        if not self._store:
            return FieldSuggestion(
                value=[], confidence="none", reason="No search store available",
            )

        query_text = body[:300]
        try:
            results = self._store.hybrid_search(query_text, limit=5)
        except Exception as e:
            logger.debug("Related page search failed: %s", e)
            return FieldSuggestion(
                value=[], confidence="low", reason=f"KB search failed: {e}",
            )

        related: list[str] = []
        for sr in results:
            doc_content = self._store.get_document(sr.file_path)
            if doc_content:
                neighbour = parse_page(doc_content)
                link = f"[[{neighbour.title}]]" if neighbour.title != "Untitled" else f"[[{sr.file_path}]]"
                if link not in related:
                    related.append(link)

        conf = "medium" if related else "none"
        reason = f"QMD search found {len(related)} page(s) with overlapping content" if related else "No similar pages found"
        if kb_status == "sparse":
            reason += " (KB is sparse — limited matches)"

        return FieldSuggestion(value=related, confidence=conf, reason=reason)

    def _suggest_owner(self, body: str, kb_status: str, hints: dict) -> FieldSuggestion:
        if hints.get("owner"):
            return FieldSuggestion(
                value=hints["owner"], confidence="high", reason="From hint"
            )

        # Check if body mentions a known team
        team_entries = self._loader.get_registry("teams")
        if team_entries:
            lower_body = body.lower()
            for entry in team_entries:
                for name in [entry.id] + entry.aliases:
                    if name.lower() in lower_body:
                        return FieldSuggestion(
                            value=entry.id, confidence="low",
                            reason=f"Content mentions team '{name}' — may be the owner",
                        )

        return FieldSuggestion(
            value=None, confidence="none",
            reason="No owner info found in content or related pages",
        )
