#!/usr/bin/env python3
import paste_macos


def test_local_workspace_title():
    matched, machine = paste_macos.resolve_paste_target("Ghostty", "Projects", [], None, "Projects")
    if not matched or machine is not None:
        raise SystemExit("workspace title should paste locally")


def test_remote_machine_title():
    remote = {"label": "build", "id": "m1"}
    matched, machine = paste_macos.resolve_paste_target(
        "Ghostty", "build: agent", [remote], None, "Projects"
    )
    if not matched or machine.get("id") != "m1":
        raise SystemExit("machine title should select the saved machine")


def test_ignores_browser():
    matched, machine = paste_macos.resolve_paste_target(
        "Google Chrome", "Projects", [], None, "Projects"
    )
    if matched or machine is not None:
        raise SystemExit("browser windows should not receive the paste")


def test_empty_title_terminal_is_local():
    matched, machine = paste_macos.resolve_paste_target("Ghostty", "", [], None, "Projects")
    if not matched or machine is not None:
        raise SystemExit("a terminal with no readable title should paste locally")


def test_unrelated_title_is_not_herdr():
    matched, _machine = paste_macos.resolve_paste_target("Ghostty", "vim notes", [], None, "Projects")
    if matched:
        raise SystemExit("an unrelated terminal title should not be treated as Herdr")


def main():
    test_local_workspace_title()
    test_remote_machine_title()
    test_ignores_browser()
    test_empty_title_terminal_is_local()
    test_unrelated_title_is_not_herdr()
    print("ok")


if __name__ == "__main__":
    main()
