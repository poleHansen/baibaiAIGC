from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from aigc_records import (
    get_round_record,
    load_records,
    normalize_record_status,
    set_docx_output_path,
)
from aigc_round_service import (
    build_progress_path,
    get_max_rounds,
    get_prompt_mapping,
    normalize_path,
    normalize_prompt_profile,
    relative_to_root,
    run_round,
)
from docx_pipeline import read_docx_text, render_docx_from_template
from workspace_paths import intermediate_dir


Transform = Callable[[str, str, int, str], str]
ProgressCallback = Callable[[dict[str, object]], None]


@dataclass
class RoundContext:
    doc_id: str
    prompt_profile: str
    round_number: int
    prompt_path: str
    source_path: Path
    input_text_path: Path
    output_text_path: Path
    manifest_path: Path
    docx_output_path: Path | None
    source_kind: str
    extracted_from_docx: bool
    apply_mode: str | None = None
    source_round: int | None = None
    target_round: int | None = None
    revision_number: int | None = None
    target_paragraph_indexes: list[int] | None = None
    based_on_output_path: str | None = None
    based_on_manifest_path: str | None = None
    is_partial: bool = False
    is_revision: bool = False

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "prompt_profile": self.prompt_profile,
            "round": self.round_number,
            "prompt_path": self.prompt_path,
            "source_path": str(self.source_path),
            "input_text_path": str(self.input_text_path),
            "output_text_path": str(self.output_text_path),
            "manifest_path": str(self.manifest_path),
            "docx_output_path": str(self.docx_output_path) if self.docx_output_path else None,
            "source_kind": self.source_kind,
            "extracted_from_docx": self.extracted_from_docx,
            "apply_mode": self.apply_mode,
            "source_round": self.source_round,
            "target_round": self.target_round,
            "revision_number": self.revision_number,
            "target_paragraph_indexes": self.target_paragraph_indexes,
            "based_on_output_path": self.based_on_output_path,
            "based_on_manifest_path": self.based_on_manifest_path,
            "is_partial": self.is_partial,
            "is_revision": self.is_revision,
        }


@dataclass
class DocumentRoundState:
    doc_id: str
    prompt_profile: str
    completed_rounds: list[int]
    next_round: int | None
    is_complete: bool


def get_document_round_state(doc_id: str, prompt_profile: str = "cn") -> DocumentRoundState:
    normalized_prompt_profile = normalize_prompt_profile(prompt_profile)
    max_rounds = get_max_rounds(normalized_prompt_profile)
    rounds = _get_rounds(doc_id)
    completed = sorted(
        round_item.get("round")
        for round_item in rounds
        if isinstance(round_item, dict)
        and isinstance(round_item.get("round"), int)
        and str(round_item.get("prompt_profile", "cn") or "cn").strip().lower() == normalized_prompt_profile
        and normalize_record_status(round_item.get("status")) == "completed"
        and 1 <= int(round_item.get("round")) <= max_rounds
    )
    for expected in range(1, max_rounds + 1):
        if expected not in completed:
            return DocumentRoundState(
                doc_id=doc_id,
                prompt_profile=normalized_prompt_profile,
                completed_rounds=completed,
                next_round=expected,
                is_complete=False,
            )
    return DocumentRoundState(
        doc_id=doc_id,
        prompt_profile=normalized_prompt_profile,
        completed_rounds=completed,
        next_round=None,
        is_complete=True,
    )


def detect_next_round(doc_id: str, prompt_profile: str = "cn") -> int:
    state = get_document_round_state(doc_id, prompt_profile=prompt_profile)
    if state.next_round is None:
        raise ValueError(f"Document already completed all {get_max_rounds(prompt_profile)} rounds: {doc_id}")
    return state.next_round


def build_round_context(source_path: Path | str, round_number: int | None = None, prompt_profile: str = "cn") -> RoundContext:
    normalized_source = normalize_path(Path(source_path))
    doc_id = _build_doc_id(normalized_source)
    normalized_prompt_profile = normalize_prompt_profile(prompt_profile)
    prompts = get_prompt_mapping(normalized_prompt_profile)
    resolved_round = round_number or detect_next_round(doc_id, prompt_profile=normalized_prompt_profile)

    if resolved_round not in prompts:
        raise ValueError(f"Round {resolved_round} is not available for document: {doc_id}")

    if resolved_round == 1:
        input_text_path, extracted_from_docx = ensure_skill_input_text(normalized_source)
    else:
        previous_round = resolved_round - 1
        input_text_path = _previous_round_output_path(doc_id, previous_round)
        extracted_from_docx = False

    stem = _doc_stem(doc_id)
    output_text_path = intermediate_dir() / f"{stem}_round{resolved_round}.txt"
    manifest_path = intermediate_dir() / f"{stem}_round{resolved_round}_manifest.json"
    docx_output_path = _build_docx_output_path(normalized_source, stem, resolved_round)

    return RoundContext(
        doc_id=doc_id,
        prompt_profile=normalized_prompt_profile,
        round_number=resolved_round,
        prompt_path=prompts[resolved_round],
        source_path=normalized_source,
        input_text_path=input_text_path,
        output_text_path=output_text_path,
        manifest_path=manifest_path,
        docx_output_path=docx_output_path,
        source_kind=normalized_source.suffix.lower() or ".txt",
        extracted_from_docx=extracted_from_docx,
    )


def build_execution_context(
    source_path: Path | str,
    round_number: int | None = None,
    prompt_profile: str = "cn",
    execution_options: dict | None = None,
) -> RoundContext:
    if not execution_options or not execution_options.get("applyMode"):
        return _build_round_context_with_resume(
            source_path,
            round_number=round_number,
            prompt_profile=prompt_profile,
        )
    return _build_targeted_context(
        source_path,
        prompt_profile=prompt_profile,
        execution_options=execution_options,
    )


def ensure_skill_input_text(source_path: Path | str) -> tuple[Path, bool]:
    normalized_source = normalize_path(Path(source_path))
    suffix = normalized_source.suffix.lower()

    if suffix == ".txt":
        return normalized_source, False

    if suffix == ".docx":
        intermediate_dir().mkdir(parents=True, exist_ok=True)
        extracted_path = intermediate_dir() / f"{normalized_source.stem}_extracted.txt"
        extracted_path.write_text(read_docx_text(normalized_source), encoding="utf-8")
        return extracted_path, True

    raise ValueError(f"Unsupported input type for skill mode: {normalized_source}")


def _build_round_context_with_resume(
    source_path: Path | str,
    round_number: int | None = None,
    prompt_profile: str = "cn",
) -> RoundContext:
    context = build_round_context(source_path, round_number=round_number, prompt_profile=prompt_profile)
    progress_path = build_progress_path(context.manifest_path)
    if not progress_path.exists():
        return context

    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return context
    if not isinstance(payload, dict):
        return context

    target_paragraph_indexes = payload.get("target_paragraph_indexes")
    based_on_output_path = payload.get("based_on_output_path")
    based_on_manifest_path = payload.get("based_on_manifest_path")
    apply_mode = str(payload.get("apply_mode", "") or "") or None
    if not apply_mode or not isinstance(based_on_output_path, str) or not based_on_output_path.strip():
        return context

    context.input_text_path = normalize_path(Path(based_on_output_path))
    context.apply_mode = apply_mode
    context.source_round = _coerce_int(payload.get("source_round"))
    context.target_round = _coerce_int(payload.get("target_round"))
    context.target_paragraph_indexes = _normalize_target_paragraph_indexes(target_paragraph_indexes)
    context.based_on_output_path = normalize_path(Path(based_on_output_path)).as_posix()
    if isinstance(based_on_manifest_path, str) and based_on_manifest_path.strip():
        context.based_on_manifest_path = normalize_path(Path(based_on_manifest_path)).as_posix()
    context.is_partial = bool(context.target_paragraph_indexes)
    return context


def _build_targeted_context(
    source_path: Path | str,
    *,
    prompt_profile: str,
    execution_options: dict,
) -> RoundContext:
    normalized_source = normalize_path(Path(source_path))
    doc_id = _build_doc_id(normalized_source)
    normalized_prompt_profile = normalize_prompt_profile(prompt_profile)
    prompts = get_prompt_mapping(normalized_prompt_profile)

    apply_mode = str(execution_options.get("applyMode", "") or "").strip()
    source_round = _required_int(execution_options.get("sourceRound"), "sourceRound")
    target_round = _required_int(execution_options.get("targetRound"), "targetRound")
    target_paragraph_indexes = _normalize_target_paragraph_indexes(execution_options.get("targetParagraphIndexes"))
    based_on_output_path = _required_path(execution_options.get("basedOnOutputPath"), "basedOnOutputPath")
    based_on_manifest_path = _required_path(execution_options.get("basedOnManifestPath"), "basedOnManifestPath")

    if apply_mode not in {"current_round_revision", "next_round_partial"}:
        raise ValueError(f"Unsupported applyMode: {apply_mode}")
    if not target_paragraph_indexes:
        raise ValueError("targetParagraphIndexes must contain at least one paragraph.")
    if target_round not in prompts:
        raise ValueError(f"Round {target_round} is not available for prompt profile {normalized_prompt_profile}.")

    if apply_mode == "current_round_revision":
        if target_round != source_round:
            raise ValueError("current_round_revision requires targetRound to equal sourceRound.")
        revision_number = _resolve_revision_number(
            doc_id,
            source_round,
            based_on_output_path=based_on_output_path,
            based_on_manifest_path=based_on_manifest_path,
            target_paragraph_indexes=target_paragraph_indexes,
        )
        output_text_path = intermediate_dir() / f"{_doc_stem(doc_id)}_round{target_round}_rev{revision_number}.txt"
        manifest_path = intermediate_dir() / f"{_doc_stem(doc_id)}_round{target_round}_rev{revision_number}_manifest.json"
        return RoundContext(
            doc_id=doc_id,
            prompt_profile=normalized_prompt_profile,
            round_number=target_round,
            prompt_path=prompts[target_round],
            source_path=normalized_source,
            input_text_path=based_on_output_path,
            output_text_path=output_text_path,
            manifest_path=manifest_path,
            docx_output_path=_build_docx_output_path(
                normalized_source,
                _doc_stem(doc_id),
                target_round,
                revision_number,
            ),
            source_kind=normalized_source.suffix.lower() or ".txt",
            extracted_from_docx=False,
            apply_mode=apply_mode,
            source_round=source_round,
            target_round=target_round,
            revision_number=revision_number,
            target_paragraph_indexes=target_paragraph_indexes,
            based_on_output_path=str(based_on_output_path),
            based_on_manifest_path=str(based_on_manifest_path),
            is_partial=True,
            is_revision=True,
        )

    if target_round != source_round + 1:
        raise ValueError("next_round_partial requires targetRound to equal sourceRound + 1.")
    target_round_record = get_round_record(doc_id, target_round, prompt_profile=normalized_prompt_profile)
    if target_round_record is not None:
        raise ValueError(f"Round {target_round} already exists for document: {doc_id}")

    output_text_path = intermediate_dir() / f"{_doc_stem(doc_id)}_round{target_round}.txt"
    manifest_path = intermediate_dir() / f"{_doc_stem(doc_id)}_round{target_round}_manifest.json"
    return RoundContext(
        doc_id=doc_id,
        prompt_profile=normalized_prompt_profile,
        round_number=target_round,
        prompt_path=prompts[target_round],
        source_path=normalized_source,
        input_text_path=based_on_output_path,
        output_text_path=output_text_path,
        manifest_path=manifest_path,
        docx_output_path=_build_docx_output_path(
            normalized_source,
            _doc_stem(doc_id),
            target_round,
        ),
        source_kind=normalized_source.suffix.lower() or ".txt",
        extracted_from_docx=False,
        apply_mode=apply_mode,
        source_round=source_round,
        target_round=target_round,
        target_paragraph_indexes=target_paragraph_indexes,
        based_on_output_path=str(based_on_output_path),
        based_on_manifest_path=str(based_on_manifest_path),
        is_partial=True,
        is_revision=False,
    )


def _required_int(value: object, field_name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer.")
    return value


def _coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _required_path(value: object, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required.")
    return normalize_path(Path(value))


def _normalize_target_paragraph_indexes(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    indexes = sorted({int(item) for item in value if isinstance(item, int)})
    return indexes


def _resolve_revision_number(
    doc_id: str,
    round_number: int,
    *,
    based_on_output_path: Path,
    based_on_manifest_path: Path,
    target_paragraph_indexes: list[int],
) -> int:
    existing = _find_matching_incomplete_revision(
        doc_id,
        round_number,
        based_on_output_path=based_on_output_path,
        based_on_manifest_path=based_on_manifest_path,
        target_paragraph_indexes=target_paragraph_indexes,
    )
    if existing is not None:
        return existing

    max_revision = 0
    round_record = get_round_record(doc_id, round_number)
    if isinstance(round_record, dict):
        revisions = round_record.get("revisions")
        if isinstance(revisions, list):
            for revision in revisions:
                if isinstance(revision, dict) and isinstance(revision.get("revision_number"), int):
                    max_revision = max(max_revision, int(revision["revision_number"]))

    stem = _doc_stem(doc_id)
    for manifest_path in intermediate_dir().glob(f"{stem}_round{round_number}_rev*_manifest.json"):
        revision_number = _extract_revision_number_from_manifest(manifest_path)
        if revision_number is not None:
            max_revision = max(max_revision, revision_number)
    return max_revision + 1


def _find_matching_incomplete_revision(
    doc_id: str,
    round_number: int,
    *,
    based_on_output_path: Path,
    based_on_manifest_path: Path,
    target_paragraph_indexes: list[int],
) -> int | None:
    stem = _doc_stem(doc_id)
    for manifest_path in intermediate_dir().glob(f"{stem}_round{round_number}_rev*_manifest.json"):
        revision_number = _extract_revision_number_from_manifest(manifest_path)
        if revision_number is None:
            continue
        progress_path = build_progress_path(manifest_path)
        if not progress_path.exists():
            continue
        try:
            payload = json.loads(progress_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status", "") or "") == "completed":
            continue
        payload_targets = _normalize_target_paragraph_indexes(payload.get("target_paragraph_indexes"))
        payload_output_path = payload.get("based_on_output_path")
        payload_manifest_path = payload.get("based_on_manifest_path")
        if payload_targets != target_paragraph_indexes:
            continue
        if not isinstance(payload_output_path, str) or normalize_path(Path(payload_output_path)) != based_on_output_path:
            continue
        if not isinstance(payload_manifest_path, str) or normalize_path(Path(payload_manifest_path)) != based_on_manifest_path:
            continue
        return revision_number
    return None


def _extract_revision_number_from_manifest(path: Path) -> int | None:
    stem = path.stem
    if "_rev" not in stem:
        return None
    suffix = stem.split("_rev", 1)[1]
    revision_text = suffix.split("_", 1)[0]
    if not revision_text.isdigit():
        return None
    return int(revision_text)


def run_skill_round(
    source_path: Path | str,
    transform: Transform,
    round_number: int | None = None,
    prompt_profile: str = "cn",
    progress_callback: ProgressCallback | None = None,
    execution_options: dict | None = None,
) -> dict:
    context = build_execution_context(
        source_path,
        round_number=round_number,
        prompt_profile=prompt_profile,
        execution_options=execution_options,
    )
    result = run_round(
        doc_id=context.doc_id,
        round_number=context.round_number,
        input_path=context.input_text_path,
        output_path=context.output_text_path,
        manifest_path=context.manifest_path,
        transform=transform,
        prompt_profile=context.prompt_profile,
        progress_callback=progress_callback,
        apply_mode=context.apply_mode,
        source_round=context.source_round,
        target_round=context.target_round,
        revision_number=context.revision_number,
        target_paragraph_indexes=context.target_paragraph_indexes,
        based_on_output_path=context.based_on_output_path,
        based_on_manifest_path=context.based_on_manifest_path,
    )
    if context.docx_output_path is not None:
        render_docx_from_template(
            context.source_path,
            context.output_text_path,
            context.docx_output_path,
            context.manifest_path,
        )
        set_docx_output_path(
            context.doc_id,
            context.round_number,
            relative_to_root(context.docx_output_path),
            revision_number=context.revision_number,
        )
        result["docx_output_path"] = str(context.docx_output_path)
    result["skill_context"] = context.to_dict()
    return result


def dump_round_plan(source_path: Path | str, round_number: int | None = None, prompt_profile: str = "cn") -> str:
    context = build_round_context(source_path, round_number=round_number, prompt_profile=prompt_profile)
    return json.dumps(context.to_dict(), ensure_ascii=False, indent=2)


def _build_doc_id(source_path: Path) -> str:
    return relative_to_root(source_path)


def _doc_stem(doc_id: str) -> str:
    return Path(doc_id).stem


def _build_docx_output_path(
    source_path: Path,
    stem: str,
    round_number: int,
    revision_number: int | None = None,
) -> Path | None:
    if source_path.suffix.lower() != ".docx":
        return None
    revision_suffix = f"_rev{revision_number}" if revision_number is not None else ""
    return intermediate_dir() / f"{stem}_round{round_number}{revision_suffix}.docx"


def _get_rounds(doc_id: str) -> list[dict]:
    records = load_records()
    entry = records.get(doc_id, {})
    rounds = entry.get("rounds", []) if isinstance(entry, dict) else []
    return [round_item for round_item in rounds if isinstance(round_item, dict)]


def _previous_round_output_path(doc_id: str, round_number: int) -> Path:
    rounds = _get_rounds(doc_id)
    for round_item in rounds:
        if round_item.get("round") == round_number:
            output_path = round_item.get("output_path")
            if not isinstance(output_path, str) or not output_path.strip():
                break
            return normalize_path(Path(output_path))
    raise ValueError(f"Round {round_number} output not found for document: {doc_id}")
