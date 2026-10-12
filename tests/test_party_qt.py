from __future__ import annotations

from dataclasses import replace
import importlib
import os
from pathlib import Path

import pytest

from PySide6.QtGui import QFont, QFontDatabase, QRawFont

from retroarch_overlay.models import OverlaySnapshot
from retroarch_overlay.presentation.qt import PanelDocumentView


@pytest.mark.parametrize("width", [360, 760])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_party_details_and_meters_render_in_shared_host(qtbot, owned_rom, plugin_package: str,
                                                        width: int, theme: str) -> None:
    state = importlib.import_module(f"{plugin_package}.game.state")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    presenter = importlib.import_module(f"{plugin_package}.game.presentation")
    helpers = importlib.import_module("test_party")
    party = state.read_party(bytes(helpers._snapshot()), labels.NativeNames(owned_rom))
    view = PanelDocumentView()
    qtbot.addWidget(view)
    font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename, family in (("segoeui.ttf", "Segoe UI"), ("seguisym.ttf", "Segoe UI Symbol")):
        if (font_directory / filename).is_file() and family not in QFontDatabase.families():
            handle = QFontDatabase.addApplicationFont(str(font_directory / filename))
            assert handle >= 0, "Offscreen pixel acceptance requires installed text/symbol fonts"
    if "Segoe UI" in QFontDatabase.families():
        view.setFont(QFont("Segoe UI", 10))
    glyphs = QRawFont.fromFont(view.font()).glyphIndexesForString("Dragon Quest V")
    assert len(set(glyphs)) > 5, "Screenshot text is rendering as identical missing-glyph boxes"
    view.resize(width, 760)
    view.set_theme(theme)
    view.show()
    view.set_snapshot(OverlaySnapshot("Dragon Quest V", "Dragon Quest V", presenter.party_sections(party)))
    section = view.state.section_views[0]
    widget = view.section_widget(section.identity)
    qtbot.waitUntil(widget.isVisible, timeout=3000)
    action = widget.action_widget(section.actions[1].identity)
    action.toggle_button.click()
    qtbot.waitUntil(action.row_view.isVisible, timeout=3000)
    assert view.state.section_views[0].actions[1].expanded
    changed = replace(party.companions[1], hp=150)
    updated = replace(party, companions=(party.companions[0], changed, *party.companions[2:]))
    view.set_snapshot(OverlaySnapshot("Dragon Quest V", "Dragon Quest V", presenter.party_sections(updated)))
    assert view.section_widget(section.identity) is widget
    assert view.state.section_views[0].actions[1].expanded
    assert view.state.section_views[0].section.rows[1].meters[0].value == 150
    following = view.section_widget(view.state.section_views[1].identity)
    qtbot.waitUntil(lambda: widget.y() < following.y(), timeout=3000)
    assert not widget.geometry().intersects(following.geometry())
    image = view.grab().toImage()
    assert image.width() == width
    colors = {image.pixelColor(column, row).name()
              for row in range(0, image.height(), 3) for column in range(0, image.width(), 3)}
    assert presenter.HP_COLOR.lower() in colors
    directory = Path(__file__).resolve().parents[1] / "native-maps/diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    assert image.save(str(directory / f"party-{owned_rom.md5[:8]}-{width}-{theme}.png"))