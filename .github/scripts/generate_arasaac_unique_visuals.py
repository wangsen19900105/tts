#!/usr/bin/env python3
"""Build a one-file-per-unique-visual ARASAAC review archive."""

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
from datetime import datetime, timezone


EXPECTED_INPUT_ENTRIES = 7_369
EXPECTED_UNIQUE_VISUALS = 5_805
EXPECTED_REMOVED_DUPLICATES = 1_564
EXPECTED_DUPLICATE_GROUPS = 1_233
OUTPUT_ROOT = "ARASAAC_唯一画面_彩色平涂优先_128px_2026-10-10"
FIXED_ZIP_TIME = (2026, 10, 10, 0, 0, 0)


def csv_bytes(rows: list[list[object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerows(rows)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def normalized_chinese(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"[，。！？、；：,.!?;:\s]+", "", value).strip()


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


def sorted_visual_group(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    category_counts = Counter(str(entry["categoryEnglish"]) for entry in entries)
    chinese_counts = Counter(normalized_chinese(str(entry["chinese"])) for entry in entries)
    return sorted(
        entries,
        key=lambda entry: (
            -category_counts[str(entry["categoryEnglish"])],
            -chinese_counts[normalized_chinese(str(entry["chinese"]))],
            *canonical_score(entry),
        ),
    )


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def zip_info(name: str, *, directory: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = ((0o40755 if directory else 0o100644) << 16) | (
        0x10 if directory else 0
    )
    return info


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: generate_arasaac_unique_visuals.py <source-v2.zip> <output.zip>"
        )

    source_path, output_path = sys.argv[1:]
    if os.path.exists(output_path):
        raise RuntimeError(f"Output already exists: {output_path}")

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

        groups: dict[str, list[dict[str, object]]] = defaultdict(list)
        for entry in source_entries:
            groups[str(entry["selectedSha256"])].append(entry)
        if len(groups) != EXPECTED_UNIQUE_VISUALS:
            raise RuntimeError(
                f"Expected {EXPECTED_UNIQUE_VISUALS} unique visuals, found {len(groups)}"
            )

        retained_entries: list[dict[str, object]] = []
        image_items: list[tuple[str, bytes]] = []
        alias_rows: list[dict[str, str]] = []
        jpeg_hashes: set[str] = set()
        normalized_destinations: set[str] = set()
        duplicate_group_count = 0

        for visual_sha256, unsorted_group in sorted(groups.items()):
            group = sorted_visual_group(unsorted_group)
            retained = group[0]
            aliases = group[1:]
            if aliases:
                duplicate_group_count += 1

            relative_preview = str(retained["selectedPreview"]).replace("\\", "/")
            source_preview = source_root + relative_preview
            image_data = source_archive.read(source_preview)
            jpeg_sha256 = hashlib.sha256(image_data).hexdigest()
            if jpeg_sha256 in jpeg_hashes:
                raise RuntimeError(
                    f"Duplicate JPEG remained after source SHA dedupe: {retained['term']}"
                )
            jpeg_hashes.add(jpeg_sha256)

            normalized_destination = unicodedata.normalize(
                "NFD", relative_preview
            ).casefold()
            if normalized_destination in normalized_destinations:
                raise RuntimeError(f"Duplicate output path: {relative_preview}")
            normalized_destinations.add(normalized_destination)
            image_items.append((f"{OUTPUT_ROOT}/{relative_preview}", image_data))

            all_labels = [
                {
                    "term": entry["term"],
                    "chinese": entry["chinese"],
                    "selectedSourceFile": entry["selectedSourceFile"],
                    "originalPreview": entry["selectedPreview"],
                    "categoryChinese": entry["categoryChinese"],
                    "categoryEnglish": entry["categoryEnglish"],
                }
                for entry in group
            ]
            retained_entry = dict(retained)
            retained_entry.update(
                {
                    "retainedPreview": relative_preview,
                    "identicalVisualLabelCount": len(group),
                    "aliases": all_labels[1:],
                    "canonicalSelectionRule": (
                        "同一原图 SHA-256 仅保留一份；优先多数分类与中文标签，"
                        "再优先无句末标点、无缩写、词形简洁的英文标签"
                    ),
                }
            )
            retained_entries.append(retained_entry)

            for alias in aliases:
                alias_rows.append(
                    {
                        "retainedChinese": str(retained["chinese"]),
                        "retainedTerm": str(retained["term"]),
                        "retainedPreview": relative_preview,
                        "aliasChinese": str(alias["chinese"]),
                        "aliasTerm": str(alias["term"]),
                        "aliasOriginalPreview": str(alias["selectedPreview"]),
                        "selectedSha256": visual_sha256,
                        "relation": "原始 PNG 内容完全相同",
                    }
                )

        retained_entries.sort(key=lambda entry: str(entry["retainedPreview"]).casefold())
        image_items.sort(key=lambda item: item[0].casefold())
        alias_rows.sort(key=lambda row: (row["retainedPreview"].casefold(), row["aliasTerm"]))

        removed_duplicate_count = len(source_entries) - len(retained_entries)
        if removed_duplicate_count != EXPECTED_REMOVED_DUPLICATES:
            raise RuntimeError(
                f"Expected {EXPECTED_REMOVED_DUPLICATES} removed duplicates, "
                f"found {removed_duplicate_count}"
            )
        if duplicate_group_count != EXPECTED_DUPLICATE_GROUPS:
            raise RuntimeError(
                f"Expected {EXPECTED_DUPLICATE_GROUPS} duplicate groups, "
                f"found {duplicate_group_count}"
            )
        if len(jpeg_hashes) != EXPECTED_UNIQUE_VISUALS:
            raise RuntimeError("Output JPEG hashes are not unique")

        summary = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "inputEntryCount": len(source_entries),
            "retainedUniqueVisualCount": len(retained_entries),
            "removedDuplicateFileCount": removed_duplicate_count,
            "duplicateVisualGroupCount": duplicate_group_count,
            "preservedVocabularyLabelCount": len(source_entries),
            "jpegContentHashCount": len(jpeg_hashes),
            "dedupeKey": "selected original PNG SHA-256",
            "exactDuplicateImagesRemaining": 0,
            "aliasesPreservedInManifestAndCsv": True,
            "note": (
                "这里只删除内容完全相同的重复画面。不同画面即使词义近似也暂未自动删除，"
                "以避免误合并。"
            ),
        }

        index_rows: list[list[object]] = [
            [
                "保留中文名",
                "保留英文词条",
                "保留图片",
                "分类中文",
                "Category English",
                "同图词条数",
                "同图中文别名",
                "同图英文别名",
                "原图SHA-256",
            ]
        ]
        for entry in retained_entries:
            index_rows.append(
                [
                    entry["chinese"],
                    entry["term"],
                    entry["retainedPreview"],
                    entry["categoryChinese"],
                    entry["categoryEnglish"],
                    entry["identicalVisualLabelCount"],
                    " | ".join(str(alias["chinese"]) for alias in entry["aliases"]),
                    " | ".join(str(alias["term"]) for alias in entry["aliases"]),
                    entry["selectedSha256"],
                ]
            )

        aliases_csv_rows: list[list[object]] = [
            [
                "保留中文名",
                "保留英文词条",
                "保留图片",
                "合并中文别名",
                "合并英文别名",
                "原重复图片",
                "原图SHA-256",
                "合并依据",
            ]
        ]
        aliases_csv_rows.extend(
            [
                row["retainedChinese"],
                row["retainedTerm"],
                row["retainedPreview"],
                row["aliasChinese"],
                row["aliasTerm"],
                row["aliasOriginalPreview"],
                row["selectedSha256"],
                row["relation"],
            ]
            for row in alias_rows
        )

        category_stats: dict[tuple[str, str], dict[str, object]] = {}
        for entry in retained_entries:
            key = (str(entry["categoryChinese"]), str(entry["categoryEnglish"]))
            stat = category_stats.setdefault(
                key,
                {
                    "categoryChinese": key[0],
                    "categoryEnglish": key[1],
                    "retainedVisuals": 0,
                    "mergedAliasLabels": 0,
                },
            )
            stat["retainedVisuals"] = int(stat["retainedVisuals"]) + 1
            stat["mergedAliasLabels"] = int(stat["mergedAliasLabels"]) + len(
                entry["aliases"]
            )
        category_rows: list[list[object]] = [
            ["分类中文", "Category English", "保留唯一画面数", "合并同图别名数"]
        ]
        for stat in sorted(
            category_stats.values(), key=lambda item: str(item["categoryEnglish"]).casefold()
        ):
            category_rows.append(
                [
                    stat["categoryChinese"],
                    stat["categoryEnglish"],
                    stat["retainedVisuals"],
                    stat["mergedAliasLabels"],
                ]
            )

        readme = f"""ARASAAC 唯一画面、彩色平涂优先预览包

本版修正了上一版“按英文词条保留，导致同一画面重复出现”的问题。

处理结果：
- 输入词条：{len(source_entries)}
- 保留唯一画面：{len(retained_entries)}
- 删除完全相同的重复图片文件：{removed_duplicate_count}
- 涉及重复画面的分组：{duplicate_group_count}
- 包内 JPG 内容哈希全部唯一，重复图片剩余：0
- 被合并的英文与中文词条没有丢失，保存在 ALIASES_同图词条.csv 和 selection-manifest.json

用户指出的示例均已合并：
- sorry / sorry! / i'm sorry!
- verb / verbs
- congratulations / congratulations!
- very well / very well!
- what is that / what's that
- what is your e- mail / what is your e- mail address

边界说明：本版仅自动删除原始 PNG SHA-256 完全相同的画面。不同画面即使词义近似，也没有自动删除，以避免把“笑/微笑”“生气/暴怒”等细微含义误合并。

文件名继续使用“中文@英文原文.jpg”。同图有多个词条时，文件名保留较简洁的一个，其余词条写入别名清单。

图形作者：Sergio Palao
来源：ARASAAC（https://arasaac.org/）
许可：CC BY-NC-SA。仅限非商业用途并须署名、相同方式共享。
""".encode("utf-8")

        metadata: dict[str, bytes] = {
            "SUMMARY.json": json_bytes(summary),
            "selection-manifest.json": json_bytes(
                {"summary": summary, "entries": retained_entries}
            ),
            "INDEX_唯一画面清单.csv": csv_bytes(index_rows),
            "ALIASES_同图词条.csv": csv_bytes(aliases_csv_rows),
            "INDEX_分类去重统计.csv": csv_bytes(category_rows),
            "README_说明.txt": readme,
        }
        for file_name in ["_README_TERMS_OF_USE.txt", "SELECTION_OVERRIDES.json"]:
            source_name = source_root + file_name
            if source_name in source_archive.namelist():
                metadata[file_name] = source_archive.read(source_name)

    with zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as output_archive:
        for output_name, image_data in image_items:
            output_archive.writestr(zip_info(output_name), image_data)
        for file_name, data in sorted(metadata.items()):
            output_archive.writestr(zip_info(f"{OUTPUT_ROOT}/{file_name}"), data)

    with zipfile.ZipFile(output_path, "r") as result_archive:
        first_error = result_archive.testzip()
        if first_error is not None:
            raise RuntimeError(f"CRC check failed for {first_error}")
        names = result_archive.namelist()
        image_names = [name for name in names if name.lower().endswith(".jpg")]
        if len(image_names) != EXPECTED_UNIQUE_VISUALS:
            raise RuntimeError(f"Expected {EXPECTED_UNIQUE_VISUALS} JPEGs, found {len(image_names)}")
        result_hashes = {
            hashlib.sha256(result_archive.read(name)).hexdigest() for name in image_names
        }
        if len(result_hashes) != EXPECTED_UNIQUE_VISUALS:
            raise RuntimeError("Duplicate JPEG content found in final archive")

    print(json.dumps({"output": output_path, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
