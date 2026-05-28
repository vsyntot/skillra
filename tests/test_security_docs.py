from __future__ import annotations

from pathlib import Path


def test_security_docs_describe_user_service_admin_sops_model() -> None:
    security = Path("docs/security.md").read_text(encoding="utf-8")
    inventory = Path("docs/secrets_inventory.md").read_text(encoding="utf-8")
    runbook = Path("docs/runbook_prod.md").read_text(encoding="utf-8")
    checklist = Path("docs/production_checklist.md").read_text(encoding="utf-8")

    for needle in ("user API", "service token", "Admin token", "SOPS + age"):
        assert needle in security

    for document in (security, inventory, runbook, checklist):
        assert "secrets-rotate-prod" in document
        assert "secrets-check-prod" in document


def test_security_docs_do_not_point_rotation_to_plain_sops_edit_first() -> None:
    inventory = Path("docs/secrets_inventory.md").read_text(encoding="utf-8")

    rotation_section = inventory.split("## Rotation Runbook", maxsplit=1)[1].split("## SOPS Bootstrap", maxsplit=1)[0]
    assert "make secrets-rotate-prod" in rotation_section
    assert "Update `secrets/prod.sops.yaml` with `sops`" not in rotation_section
