"""Unit tests for the bundled obstacle SVG library helpers."""

from __future__ import annotations

from pathlib import Path

import pipeline.media.obstacle_library as obstacle_library
import pipeline.media.svg_variant_library as svg_variant_library


def test_get_obstacle_svg_returns_known_library_asset(monkeypatch: object, tmp_path: Path) -> None:
    library_dir = tmp_path / "frontend" / "public" / "obstacles"
    library_dir.mkdir(parents=True)
    (library_dir / "wall.svg").write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(obstacle_library, "_LIBRARY_DIR", library_dir)

    assert obstacle_library.get_obstacle_svg("wall") == "<svg/>"


def test_get_obstacle_svg_returns_none_for_unknown_slug(
    monkeypatch: object, tmp_path: Path
) -> None:
    library_dir = tmp_path / "frontend" / "public" / "obstacles"
    library_dir.mkdir(parents=True)
    monkeypatch.setattr(obstacle_library, "_LIBRARY_DIR", library_dir)

    assert obstacle_library.get_obstacle_svg("dragon") is None


def test_get_obstacle_svg_randomly_chooses_between_numbered_variants(
    monkeypatch: object, tmp_path: Path
) -> None:
    library_dir = tmp_path / "frontend" / "public" / "obstacles"
    library_dir.mkdir(parents=True)
    robot_1 = library_dir / "robot.svg"
    robot_2 = library_dir / "robot-2.svg"
    robot_1.write_text("<svg>one</svg>", encoding="utf-8")
    robot_2.write_text("<svg>two</svg>", encoding="utf-8")
    monkeypatch.setattr(obstacle_library, "_LIBRARY_DIR", library_dir)

    def choose_last(items: list[Path]) -> Path:
        return items[-1]

    monkeypatch.setattr(svg_variant_library.random, "choice", choose_last)

    assert obstacle_library.get_obstacle_svg("robot") == "<svg>two</svg>"


def test_list_library_names_returns_sorted_names(monkeypatch: object, tmp_path: Path) -> None:
    library_dir = tmp_path / "frontend" / "public" / "obstacles"
    library_dir.mkdir(parents=True)
    (library_dir / "wall.svg").write_text("<svg/>", encoding="utf-8")
    (library_dir / "bird.svg").write_text("<svg/>", encoding="utf-8")
    (library_dir / "bird-2.svg").write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(obstacle_library, "_LIBRARY_DIR", library_dir)

    assert obstacle_library.list_library_names() == ["bird", "wall"]
