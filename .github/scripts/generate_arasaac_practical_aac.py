#!/usr/bin/env python3
"""Build a compact, auditable ARASAAC vocabulary review archive.

The input is the fixed one-file-per-term v2 archive.  Curation decisions live in
JSON so that uncommon-term removal, semantic merges, translation corrections,
and category corrections remain reviewable instead of being hidden in code.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict


EXPECTED_INPUT_ENTRIES = 7_369
EXPECTED_INPUT_UNIQUE_VISUALS = 5_805
EXPECTED_SOURCE_SHA256 = "5684591cc3774d8353654dd0619f3232bd9be256d20c4b7c1ee5b56841a0255f"
EXPECTED_TERMS_OF_USE_SHA256 = "1ed1917f36734b3e766143e0b85646921dd9f154d9302e1998c75f5fb0359907"
OUTPUT_ROOT = "ARASAAC_实用AAC精选_彩色平涂优先_128px_2026-10-10"
FIXED_ZIP_TIME = (2026, 10, 10, 0, 0, 0)
FIXED_GENERATED_AT = "2026-10-10T00:00:00Z"


def csv_bytes(rows: list[list[object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerows(rows)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def norm_term(value: str) -> str:
    # Term keys are intentionally case-sensitive.  The source contains real
    # contrasts such as Turkey/turkey, US/us, and A/a; case folding would merge
    # unrelated concepts.  Case-only merges must be explicit in the policy.
    return unicodedata.normalize("NFKC", value).strip()


def canonical_score(entry: dict[str, object]) -> tuple[object, ...]:
    term = unicodedata.normalize("NFKC", str(entry["term"])).strip()
    return (
        int(bool(re.search(r"[!?.,;:]$", term))),
        int(bool(re.search(r"['’]", term))),
        int(bool(re.fullmatch(r"\(.+\)", term))),
        int(term != term.lower()),
        sum(not character.isalnum() and not character.isspace() for character in term),
        len(term.split()),
        len(term),
        term.casefold(),
        term,
    )


def safe_component(value: str) -> str:
    value = unicodedata.normalize("NFC", value).strip()
    value = value.translate(
        str.maketrans(
            {
                "/": "／",
                "\\": "＼",
                ":": "：",
                "*": "＊",
                "?": "？",
                '"': "＂",
                "<": "＜",
                ">": "＞",
                "|": "｜",
            }
        )
    )
    value = re.sub(r"\s+", " ", value).strip(" .") or "未命名"
    encoded = value.encode("utf-8")
    if len(encoded) <= 220:
        return value
    suffix = "-" + hashlib.sha256(encoded).hexdigest()[:10]
    budget = 220 - len(suffix.encode("utf-8"))
    shortened = value
    while len(shortened.encode("utf-8")) > budget:
        shortened = shortened[:-1]
    return shortened.rstrip() + suffix


def image_file_name(chinese: str, english: str) -> str:
    stem = safe_component(chinese) + "@" + safe_component(english)
    suffix = "-" + hashlib.sha256(stem.encode("utf-8")).hexdigest()[:10]
    byte_budget = 240 - len((suffix + ".jpg").encode("utf-8"))
    if len((stem + ".jpg").encode("utf-8")) <= 240:
        return stem + ".jpg"
    shortened = stem
    while len(shortened.encode("utf-8")) > byte_budget:
        shortened = shortened[:-1]
    return shortened.rstrip(" .") + suffix + ".jpg"


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            "Usage: generate_arasaac_practical_aac.py "
            "<source-v2.zip> <curation.json> <output.zip>"
        )

    source_path, policy_path, output_path = sys.argv[1:]
    if os.path.exists(output_path):
        raise RuntimeError(f"Output already exists: {output_path}")
    source_archive_sha256 = file_sha256(source_path)
    if source_archive_sha256 != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            "Unexpected source archive SHA-256: "
            f"{source_archive_sha256} (expected {EXPECTED_SOURCE_SHA256})"
        )
    with open(policy_path, "rb") as policy_file:
        policy_data = policy_file.read()
    policy_sha256 = hashlib.sha256(policy_data).hexdigest()
    policy = json.loads(policy_data)
    expected_retained = policy.get("expectedRetainedVisualCount")
    if not isinstance(expected_retained, int) or expected_retained <= 0:
        raise RuntimeError("Policy expectedRetainedVisualCount must be a positive integer")

    remove_terms = {
        norm_term(item["term"]): item["reason"] for item in policy["removeTerms"]
    }
    if len(remove_terms) != len(policy["removeTerms"]):
        raise RuntimeError("Repeated term in removeTerms")
    chinese_overrides = {
        norm_term(term): value for term, value in policy.get("chineseOverrides", {}).items()
    }
    english_overrides = {
        norm_term(term): value for term, value in policy.get("englishOverrides", {}).items()
    }
    category_overrides = {
        norm_term(term): value for term, value in policy.get("categoryOverrides", {}).items()
    }
    exact_visual_canonical_terms = [
        norm_term(term) for term in policy.get("exactVisualCanonicalTerms", [])
    ]
    alias_to_group: dict[str, dict[str, object]] = {}
    for group in policy["semanticMergeGroups"]:
        canonical = norm_term(group["canonicalTerm"])
        terms = [canonical, *(norm_term(term) for term in group["mergedTerms"])]
        image_term = norm_term(str(group.get("imageTerm", group["canonicalTerm"])))
        if image_term not in terms:
            raise RuntimeError(
                f"Semantic imageTerm must be in its group: {group.get('imageTerm')}"
            )
        if len(set(terms)) != len(terms):
            raise RuntimeError(f"Repeated term in semantic group: {group}")
        for term in terms:
            previous = alias_to_group.setdefault(term, group)
            if previous is not group:
                raise RuntimeError(f"Term appears in multiple semantic groups: {term}")
    removed_semantic_overlap = sorted(set(remove_terms) & set(alias_to_group))
    if removed_semantic_overlap:
        raise RuntimeError(
            f"Removed terms also appear in semantic groups: {removed_semantic_overlap}"
        )

    with zipfile.ZipFile(source_path, "r") as source_archive:
        manifest_names = [
            name
            for name in source_archive.namelist()
            if name.endswith("/selection-manifest.json")
        ]
        if len(manifest_names) != 1:
            raise RuntimeError(f"Expected one source manifest, found {len(manifest_names)}")
        manifest_name = manifest_names[0]
        source_root = manifest_name.removesuffix("selection-manifest.json")
        source_document = json.loads(source_archive.read(manifest_name))
        source_entries = source_document["entries"]
        if len(source_entries) != EXPECTED_INPUT_ENTRIES:
            raise RuntimeError(
                f"Expected {EXPECTED_INPUT_ENTRIES} input entries, found {len(source_entries)}"
            )

        terms: dict[str, dict[str, object]] = {}
        entries_by_sha: dict[str, list[dict[str, object]]] = defaultdict(list)
        for raw_entry in source_entries:
            entry = dict(raw_entry)
            key = norm_term(str(entry["term"]))
            if key in terms:
                raise RuntimeError(f"Duplicate normalized source term: {entry['term']}")
            terms[key] = entry
            entries_by_sha[str(entry["selectedSha256"])].append(entry)
        if len(entries_by_sha) != EXPECTED_INPUT_UNIQUE_VISUALS:
            raise RuntimeError(
                f"Expected {EXPECTED_INPUT_UNIQUE_VISUALS} source visuals, "
                f"found {len(entries_by_sha)}"
            )

        unknown_removed = sorted(set(remove_terms) - set(terms))
        if unknown_removed:
            raise RuntimeError(f"Unknown removed terms: {unknown_removed}")
        for override_name, overrides in (
            ("Chinese", chinese_overrides),
            ("English", english_overrides),
            ("category", category_overrides),
        ):
            unknown_overrides = sorted(set(overrides) - set(terms))
            if unknown_overrides:
                raise RuntimeError(
                    f"Unknown {override_name} override terms: {unknown_overrides}"
                )
        unknown_semantic = sorted(set(alias_to_group) - set(terms))
        if unknown_semantic:
            raise RuntimeError(f"Unknown semantic terms: {unknown_semantic}")
        unknown_image_terms = sorted(
            {
                norm_term(str(group["imageTerm"]))
                for group in policy["semanticMergeGroups"]
                if "imageTerm" in group
            }
            - set(terms)
        )
        if unknown_image_terms:
            raise RuntimeError(f"Unknown semantic image terms: {unknown_image_terms}")
        unknown_exact_canonicals = sorted(set(exact_visual_canonical_terms) - set(terms))
        if unknown_exact_canonicals:
            raise RuntimeError(
                f"Unknown exact-visual canonical terms: {unknown_exact_canonicals}"
            )
        exact_canonical_by_sha: dict[str, dict[str, object]] = {}
        for term in exact_visual_canonical_terms:
            entry = terms[term]
            sha = str(entry["selectedSha256"])
            previous = exact_canonical_by_sha.setdefault(sha, entry)
            if previous is not entry:
                raise RuntimeError(
                    "Multiple canonical overrides for exact visual "
                    f"{sha}: {previous['term']} and {entry['term']}"
                )
        semantic_group_by_target_sha: dict[str, dict[str, object]] = {}
        for group in policy["semanticMergeGroups"]:
            canonical = norm_term(group["canonicalTerm"])
            if canonical in remove_terms:
                raise RuntimeError(f"Semantic canonical is removed: {group['canonicalTerm']}")
            image_term = norm_term(str(group.get("imageTerm", group["canonicalTerm"])))
            if image_term in remove_terms:
                raise RuntimeError(
                    f"Semantic image term is removed: {group.get('imageTerm')}"
                )
            target_sha = str(terms[image_term]["selectedSha256"])
            previous_target_group = semantic_group_by_target_sha.setdefault(
                target_sha, group
            )
            if previous_target_group is not group:
                raise RuntimeError(
                    "Multiple semantic groups target the same visual "
                    f"{target_sha}: {previous_target_group['canonicalTerm']} and "
                    f"{group['canonicalTerm']}"
                )
            exact_canonical = exact_canonical_by_sha.get(target_sha)
            if (
                exact_canonical is not None
                and norm_term(str(exact_canonical["term"])) != canonical
            ):
                raise RuntimeError(
                    "Conflicting canonical terms for retained visual "
                    f"{target_sha}: semantic={group['canonicalTerm']}, "
                    f"exact={exact_canonical['term']}"
                )

        folder_by_category: dict[str, str] = {}
        for entry in source_entries:
            folder = str(entry["selectedPreview"]).replace("\\", "/").split("/", 1)[0]
            if (
                not folder
                or folder in {".", ".."}
                or "/" in folder
                or "\\" in folder
                or os.path.isabs(folder)
            ):
                raise RuntimeError(f"Unsafe category folder: {folder!r}")
            category = str(entry["categoryEnglish"])
            previous = folder_by_category.setdefault(category, folder)
            if previous != folder:
                raise RuntimeError(f"Category has multiple source folders: {category}")
        for category in category_overrides.values():
            if category not in folder_by_category:
                raise RuntimeError(f"Unknown category override: {category}")

        kept_labels_by_sha: dict[str, list[dict[str, object]]] = defaultdict(list)
        removed_rows: list[dict[str, object]] = []
        semantic_rows: list[dict[str, object]] = []

        for entry in source_entries:
            key = norm_term(str(entry["term"]))
            sha = str(entry["selectedSha256"])
            if key in remove_terms:
                removed_rows.append(
                    {
                        "action": "删除冷门或错误词条",
                        "term": entry["term"],
                        "chinese": entry["chinese"],
                        "originalPreview": entry["selectedPreview"],
                        "sourceSha256": sha,
                        "targetTerm": "",
                        "reason": remove_terms[key],
                    }
                )
                continue
            group = alias_to_group.get(key)
            if group is not None:
                group_canonical_key = norm_term(str(group["canonicalTerm"]))
                group_image_key = norm_term(
                    str(group.get("imageTerm", group["canonicalTerm"]))
                )
                canonical_entry = terms[group_canonical_key]
                image_entry = terms[group_image_key]
                target_sha = str(image_entry["selectedSha256"])
                if sha != target_sha:
                    moved = dict(entry)
                    moved["semanticMergeSourceSha256"] = sha
                    moved["semanticMergeReason"] = group["reason"]
                    decision_type = (
                        "imageReplacement"
                        if key == group_canonical_key
                        else "aliasMerge"
                    )
                    moved["semanticDecisionType"] = decision_type
                    kept_labels_by_sha[target_sha].append(moved)
                    semantic_rows.append(
                        {
                            "decisionType": decision_type,
                            "term": entry["term"],
                            "chinese": entry["chinese"],
                            "sourceSha256": sha,
                            "targetTerm": canonical_entry["term"],
                            "targetSha256": target_sha,
                            "reason": group["reason"],
                        }
                    )
                    removed_rows.append(
                        {
                            "action": (
                                "替换词条画面"
                                if decision_type == "imageReplacement"
                                else "跨画面语义合并"
                            ),
                            "term": entry["term"],
                            "chinese": entry["chinese"],
                            "originalPreview": entry["selectedPreview"],
                            "sourceSha256": sha,
                            "targetTerm": canonical_entry["term"],
                            "reason": group["reason"],
                        }
                    )
                    continue
                staying = dict(entry)
                if group_image_key != group_canonical_key and key == group_image_key:
                    staying["semanticDecisionType"] = "imageSource"
                    staying["semanticMergeReason"] = group["reason"]
                elif key != group_canonical_key:
                    staying["semanticDecisionType"] = "aliasOnTarget"
                    staying["semanticMergeReason"] = group["reason"]
                kept_labels_by_sha[sha].append(staying)
                continue
            kept_labels_by_sha[sha].append(entry)

        retained: list[dict[str, object]] = []
        image_items: list[tuple[str, bytes]] = []
        exact_alias_rows: list[dict[str, object]] = []
        corrections_rows: list[dict[str, object]] = []
        output_paths: set[str] = set()
        output_hashes: set[str] = set()

        for sha, labels in sorted(kept_labels_by_sha.items()):
            if not labels:
                continue
            original_labels = entries_by_sha.get(sha, [])
            physical_candidates = [label for label in labels if label in original_labels]
            group_override = semantic_group_by_target_sha.get(sha)
            if not physical_candidates:
                if group_override is None:
                    raise RuntimeError(
                        f"No physical source label remains for retained visual {sha}"
                    )
                physical_candidates = [
                    terms[
                        norm_term(
                            str(
                                group_override.get(
                                    "imageTerm", group_override["canonicalTerm"]
                                )
                            )
                        )
                    ]
                ]
            if group_override is not None:
                canonical = terms[norm_term(str(group_override["canonicalTerm"]))]
                image_entry = terms[
                    norm_term(
                        str(group_override.get("imageTerm", group_override["canonicalTerm"]))
                    )
                ]
            elif sha in exact_canonical_by_sha:
                canonical = exact_canonical_by_sha[sha]
                image_entry = canonical
                if canonical not in labels:
                    raise RuntimeError(
                        f"Exact visual canonical was removed or moved: {canonical['term']}"
                    )
            else:
                canonical = sorted(physical_candidates, key=canonical_score)[0]
                image_entry = canonical

            canonical_key = norm_term(str(canonical["term"]))
            display_term = english_overrides.get(canonical_key, str(canonical["term"]))
            chinese = chinese_overrides.get(canonical_key, str(canonical["chinese"]))
            category = category_overrides.get(canonical_key, str(canonical["categoryEnglish"]))
            folder = folder_by_category[category]
            file_name = image_file_name(chinese, display_term)
            relative_path = f"{folder}/{file_name}"
            normalized_path = unicodedata.normalize("NFD", relative_path).casefold()
            if normalized_path in output_paths:
                raise RuntimeError(
                    "Output filename collision requires an explicit policy correction: "
                    f"{relative_path}"
                )
            output_paths.add(normalized_path)

            source_preview = source_root + str(image_entry["selectedPreview"]).replace("\\", "/")
            image_data = source_archive.read(source_preview)
            image_hash = hashlib.sha256(image_data).hexdigest()
            if image_hash in output_hashes:
                raise RuntimeError(f"Duplicate JPEG content remained: {canonical['term']}")
            output_hashes.add(image_hash)
            image_items.append((f"{OUTPUT_ROOT}/{relative_path}", image_data))

            label_documents: list[dict[str, object]] = []
            for label in sorted(
                labels,
                key=lambda item: (
                    norm_term(str(item["term"])) != canonical_key,
                    canonical_score(item),
                ),
            ):
                key = norm_term(str(label["term"]))
                label_term = english_overrides.get(key, str(label["term"]))
                label_chinese = chinese_overrides.get(key, str(label["chinese"]))
                label_category = category_overrides.get(key, str(label["categoryEnglish"]))
                decision_type = label.get("semanticDecisionType")
                if decision_type == "imageReplacement":
                    relation = "保留词条并替换错误画面"
                elif decision_type == "aliasMerge":
                    relation = "近义或冗余画面合并"
                elif decision_type == "imageSource":
                    relation = "替换画面的来源词条"
                elif decision_type == "aliasOnTarget":
                    relation = "语义合并（原图与保留画面相同）"
                elif str(label["selectedSha256"]) == sha and key != canonical_key:
                    relation = "原始 PNG 内容完全相同"
                else:
                    relation = "保留词条"
                label_documents.append(
                    {
                        "term": label_term,
                        "originalTerm": label["term"],
                        "chinese": label_chinese,
                        "categoryEnglish": label_category,
                        "relation": relation,
                        "originalPreview": label["selectedPreview"],
                        "originalSha256": label["selectedSha256"],
                    }
                )
                if label_chinese != str(label["chinese"]):
                    corrections_rows.append(
                        {
                            "term": label["term"],
                            "field": "中文",
                            "before": label["chinese"],
                            "after": label_chinese,
                            "reason": "修正误译或消除同名冲突",
                        }
                    )
                if label_term != str(label["term"]):
                    corrections_rows.append(
                        {
                            "term": label["term"],
                            "field": "英文",
                            "before": label["term"],
                            "after": label_term,
                            "reason": "修正误名或拼写",
                        }
                    )
                if label_category != str(label["categoryEnglish"]):
                    corrections_rows.append(
                        {
                            "term": label["term"],
                            "field": "分类",
                            "before": label["categoryEnglish"],
                            "after": label_category,
                            "reason": "修正明显误分类",
                        }
                    )
                if relation == "原始 PNG 内容完全相同":
                    exact_alias_rows.append(
                        {
                            "retainedTerm": display_term,
                            "retainedOriginalTerm": canonical["term"],
                            "retainedChinese": chinese,
                            "aliasTerm": label_term,
                            "aliasOriginalTerm": label["term"],
                            "aliasChinese": label_chinese,
                            "retainedPreview": relative_path,
                            "sourceSha256": sha,
                        }
                    )

            retained.append(
                {
                    "term": display_term,
                    "originalTerm": canonical["term"],
                    "chinese": chinese,
                    "categoryEnglish": category,
                    "retainedPreview": relative_path,
                    "selectedSourceFile": image_entry["selectedSourceFile"],
                    "sourceImageTerm": image_entry["term"],
                    "selectedSha256": sha,
                    "jpegSha256": image_hash,
                    "labels": label_documents,
                }
            )

        retained_sha = {str(item["selectedSha256"]) for item in retained}
        removed_visual_count = EXPECTED_INPUT_UNIQUE_VISUALS - len(retained_sha)
        for row in removed_rows:
            if row["action"] == "跨画面语义合并":
                row["action"] = (
                    "合并语义并删除独立画面"
                    if str(row["sourceSha256"]) not in retained_sha
                    else "合并语义标签（原画面因其他词条保留）"
                )
            elif row["action"] == "替换词条画面":
                row["action"] = (
                    "替换错误画面并移除旧画面"
                    if str(row["sourceSha256"]) not in retained_sha
                    else "替换错误画面（旧画面因其他词条保留）"
                )

        retained.sort(key=lambda item: str(item["retainedPreview"]).casefold())
        image_items.sort(key=lambda item: item[0].casefold())
        removed_rows.sort(key=lambda item: (str(item["action"]), str(item["term"]).casefold()))
        semantic_rows.sort(key=lambda item: str(item["term"]).casefold())
        corrections_rows.sort(key=lambda item: (str(item["field"]), str(item["term"]).casefold()))

        expected_retained = policy.get("expectedRetainedVisualCount")
        if expected_retained is not None and len(retained) != expected_retained:
            raise RuntimeError(
                f"Expected {expected_retained} retained visuals, found {len(retained)}"
            )
        if len(retained) != len(output_hashes):
            raise RuntimeError("Retained visuals and JPEG hashes differ")

        retained_original_terms = [
            norm_term(str(label["originalTerm"]))
            for item in retained
            for label in item["labels"]
        ]
        explicitly_removed_terms = [
            norm_term(str(row["term"]))
            for row in removed_rows
            if row["action"] == "删除冷门或错误词条"
        ]
        source_term_keys = [norm_term(str(entry["term"])) for entry in source_entries]
        coverage = Counter([*retained_original_terms, *explicitly_removed_terms])
        expected_coverage = Counter(source_term_keys)
        if coverage != expected_coverage:
            missing = sorted((expected_coverage - coverage).elements())
            repeated = sorted((coverage - expected_coverage).elements())
            raise RuntimeError(
                "Source-term audit coverage mismatch: "
                f"missing={missing[:10]}, repeated={repeated[:10]}"
            )

        retained_by_source_sha = {
            str(item["selectedSha256"]): item for item in retained
        }
        for term in exact_visual_canonical_terms:
            source_sha = str(terms[term]["selectedSha256"])
            retained_item = retained_by_source_sha.get(source_sha)
            if retained_item is None:
                raise RuntimeError(f"Exact canonical visual was not retained: {term}")
            if norm_term(str(retained_item["originalTerm"])) != term:
                raise RuntimeError(
                    f"Exact canonical was not applied for {source_sha}: "
                    f"expected {term}, got {retained_item['originalTerm']}"
                )

        action_counts = Counter(str(row["action"]) for row in removed_rows)
        correction_counts = Counter(str(row["field"]) for row in corrections_rows)
        explicit_removed_rows = [
            row for row in removed_rows if row["action"] == "删除冷门或错误词条"
        ]
        explicit_source_sha = {
            str(row["sourceSha256"]) for row in explicit_removed_rows
        }
        explicit_removed_visual_sha = explicit_source_sha - retained_sha
        alias_merge_rows = [
            row for row in semantic_rows if row["decisionType"] == "aliasMerge"
        ]
        image_replacement_rows = [
            row for row in semantic_rows if row["decisionType"] == "imageReplacement"
        ]
        semantic_source_sha = {
            str(row["sourceSha256"]) for row in alias_merge_rows
        }
        semantic_removed_sha = semantic_source_sha - retained_sha
        replacement_source_sha = {
            str(row["sourceSha256"]) for row in image_replacement_rows
        }
        replacement_removed_sha = replacement_source_sha - retained_sha
        removed_or_merged_label_count = (
            len(explicitly_removed_terms) + len(alias_merge_rows)
        )
        summary = {
            "generatedAt": FIXED_GENERATED_AT,
            "sourceArchiveSha256": source_archive_sha256,
            "curationPolicySha256": policy_sha256,
            "sourceTermCount": len(source_entries),
            "sourceUniqueVisualCount": EXPECTED_INPUT_UNIQUE_VISUALS,
            "retainedPracticalVisualCount": len(retained),
            "removedVisualCount": removed_visual_count,
            "removedOrMergedLabelCount": removed_or_merged_label_count,
            "curationDecisionRowCount": len(removed_rows),
            "semanticMergedLabelCount": len(alias_merge_rows),
            "imageReplacementLabelCount": len(image_replacement_rows),
            "retainedSourceLabelCount": len(retained_original_terms),
            "explicitlyRemovedSourceLabelCount": len(explicitly_removed_terms),
            "explicitRemovalSourceVisualCount": len(explicit_source_sha),
            "explicitRemovalSourceVisualRemovedCount": len(explicit_removed_visual_sha),
            "semanticSourceVisualCount": len(semantic_source_sha),
            "semanticRemovedVisualCount": len(semantic_removed_sha),
            "imageReplacementSourceVisualCount": len(replacement_source_sha),
            "imageReplacementRemovedVisualCount": len(replacement_removed_sha),
            "exactDuplicateSourceFileCount": len(source_entries) - EXPECTED_INPUT_UNIQUE_VISUALS,
            "sourceTermsSharingExistingVisualCount": len(source_entries)
            - EXPECTED_INPUT_UNIQUE_VISUALS,
            "retainedJpegHashCount": len(output_hashes),
            "exactDuplicateImagesRemaining": 0,
            "confidenceFoldersRemoved": True,
            "actionCounts": dict(sorted(action_counts.items())),
            "appliedCorrectionCounts": dict(sorted(correction_counts.items())),
        }

        index_rows: list[list[object]] = [[
            "中文名",
            "英文词条",
            "图片路径",
            "分类",
            "保留标签数",
            "其他英文标签",
            "原图SHA-256",
            "JPG SHA-256",
        ]]
        for item in retained:
            index_rows.append(
                [
                    item["chinese"],
                    item["term"],
                    item["retainedPreview"],
                    item["categoryEnglish"],
                    len(item["labels"]),
                    " | ".join(
                        str(label["term"])
                        for label in item["labels"]
                        if norm_term(str(label["term"])) != norm_term(str(item["term"]))
                    ),
                    item["selectedSha256"],
                    item["jpegSha256"],
                ]
            )

        removed_csv_rows: list[list[object]] = [[
            "处理",
            "中文",
            "英文词条",
            "原图片",
            "原图SHA-256",
            "合并目标",
            "原因",
        ]]
        removed_csv_rows.extend(
            [
                row["action"],
                row["chinese"],
                row["term"],
                row["originalPreview"],
                row["sourceSha256"],
                row["targetTerm"],
                row["reason"],
            ]
            for row in removed_rows
        )

        semantic_csv_rows: list[list[object]] = [[
            "处理类型",
            "被合并中文",
            "被合并英文",
            "保留英文",
            "原画面SHA-256",
            "保留画面SHA-256",
            "合并原因",
        ]]
        semantic_csv_rows.extend(
            [
                (
                    "替换错误画面"
                    if row["decisionType"] == "imageReplacement"
                    else "合并近义或冗余画面"
                ),
                row["chinese"],
                row["term"],
                row["targetTerm"],
                row["sourceSha256"],
                row["targetSha256"],
                row["reason"],
            ]
            for row in semantic_rows
        )

        exact_alias_csv_rows: list[list[object]] = [[
            "保留中文",
            "保留英文",
            "保留英文原词",
            "同图中文别名",
            "同图英文别名",
            "同图英文原词",
            "保留图片",
            "原图SHA-256",
        ]]
        exact_alias_csv_rows.extend(
            [
                row["retainedChinese"],
                row["retainedTerm"],
                row["retainedOriginalTerm"],
                row["aliasChinese"],
                row["aliasTerm"],
                row["aliasOriginalTerm"],
                row["retainedPreview"],
                row["sourceSha256"],
            ]
            for row in exact_alias_rows
        )

        corrections_csv_rows: list[list[object]] = [[
            "英文词条", "修正字段", "修正前", "修正后", "原因"
        ]]
        corrections_csv_rows.extend(
            [row["term"], row["field"], row["before"], row["after"], row["reason"]]
            for row in corrections_rows
        )

        category_counts = Counter(str(item["categoryEnglish"]) for item in retained)
        category_csv_rows: list[list[object]] = [["分类", "保留图片数"]]
        category_csv_rows.extend(
            [category, count]
            for category, count in sorted(category_counts.items(), key=lambda item: item[0].casefold())
        )

        readme = f"""ARASAAC 实用 AAC 精选、彩色平涂优先预览包

这是供词表策划和非商业审核使用的紧凑版，不是原始全集。

处理结果：
- 原始词条：{len(source_entries)}
- 原始唯一画面：{EXPECTED_INPUT_UNIQUE_VISUALS}
- 精选保留画面：{len(retained)}
- 删除或合并画面：{removed_visual_count}
- 删除冷门或错误标签：{len(explicitly_removed_terms)}
- 跨画面语义合并标签：{len(alias_merge_rows)}
- 其中因语义合并而真正移除的源画面：{len(semantic_removed_sha)}
- 保留常用词但替换错误画面：{len(image_replacement_rows)}
- 包内 JPG 哈希全部唯一，完全相同的图片剩余：0

本版同时处理四类问题：
1. 相同原图只保留一份；
2. 用户不需要区分的同义、拼写、单复数和包装画面合并；
3. 西班牙地方文化、过细物种、冷门食品、专名和专业课程词移出核心包；
4. 修正明显中文误译与分类错误。

不再使用“较高置信/待人工复核”子目录。旧版所谓“较高置信”只表示自动规则命中，不能代表语义正确。

审计文件：
- INDEX_实用AAC词汇.csv：最终保留清单
- REMOVED_冷门与冗余词条.csv：所有删除与合并原因
- ALIASES_语义合并.csv：不同画面的近义合并与错误画面替换
- ALIASES_完全同图.csv：相同原图的词条别名
- CORRECTIONS_中文与分类.csv：翻译和分类修正
- CURATION_POLICY.json：本次完整规则

文件名使用“中文@最终英文词条.jpg”；上游英文原词保存在 selection-manifest.json 的 originalTerm 中。

图形作者：Sergio Palao
来源：ARASAAC（https://arasaac.org/）
许可：CC BY-NC-SA。仅限非商业用途并须署名、相同方式共享。
完整要求以随包保留的 _README_TERMS_OF_USE.txt 与 ARASAAC 官网为准。
""".encode("utf-8")

        metadata: dict[str, bytes] = {
            "SUMMARY.json": json_bytes(summary),
            "selection-manifest.json": json_bytes({"summary": summary, "entries": retained}),
            "CURATION_POLICY.json": json_bytes(policy),
            "INDEX_实用AAC词汇.csv": csv_bytes(index_rows),
            "REMOVED_冷门与冗余词条.csv": csv_bytes(removed_csv_rows),
            "ALIASES_语义合并.csv": csv_bytes(semantic_csv_rows),
            "ALIASES_完全同图.csv": csv_bytes(exact_alias_csv_rows),
            "CORRECTIONS_中文与分类.csv": csv_bytes(corrections_csv_rows),
            "INDEX_分类统计.csv": csv_bytes(category_csv_rows),
            "README_说明.txt": readme,
        }
        terms_of_use = source_root + "_README_TERMS_OF_USE.txt"
        if terms_of_use not in source_archive.namelist():
            raise RuntimeError("Source terms-of-use file is missing")
        terms_of_use_data = source_archive.read(terms_of_use)
        terms_of_use_sha256 = hashlib.sha256(terms_of_use_data).hexdigest()
        if terms_of_use_sha256 != EXPECTED_TERMS_OF_USE_SHA256:
            raise RuntimeError(
                "Unexpected terms-of-use SHA-256: "
                f"{terms_of_use_sha256} (expected {EXPECTED_TERMS_OF_USE_SHA256})"
            )
        metadata["_README_TERMS_OF_USE.txt"] = terms_of_use_data

    temporary_output_path = f"{output_path}.tmp-{os.getpid()}"
    if os.path.exists(temporary_output_path):
        raise RuntimeError(f"Temporary output already exists: {temporary_output_path}")
    try:
        with zipfile.ZipFile(
            temporary_output_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as output_archive:
            for name, data in image_items:
                output_archive.writestr(zip_info(name), data, compresslevel=6)
            for name, data in sorted(metadata.items()):
                output_archive.writestr(
                    zip_info(f"{OUTPUT_ROOT}/{name}"), data, compresslevel=6
                )

        with zipfile.ZipFile(temporary_output_path, "r") as result_archive:
            first_error = result_archive.testzip()
            if first_error is not None:
                raise RuntimeError(f"CRC check failed for {first_error}")
            image_names = [
                name
                for name in result_archive.namelist()
                if name.lower().endswith(".jpg")
            ]
            if len(image_names) != len(retained):
                raise RuntimeError(
                    f"Expected {len(retained)} JPEGs in final ZIP, "
                    f"found {len(image_names)}"
                )
            hashes = {
                hashlib.sha256(result_archive.read(name)).hexdigest()
                for name in image_names
            }
            if len(hashes) != len(image_names):
                raise RuntimeError("Duplicate JPEG content found in final ZIP")
        os.replace(temporary_output_path, output_path)
    finally:
        if os.path.exists(temporary_output_path):
            os.unlink(temporary_output_path)

    print(json.dumps({"output": output_path, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
