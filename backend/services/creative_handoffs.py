"""Read-only handoff preparation and revalidation against protected source receipts."""

from types import SimpleNamespace
from services.handoff_contracts import CreativeReference, HandoffDraft
from services.tools import ServiceError


class CreativeHandoffs:
    def __init__(self, app):
        self.app = app

    def source(self, owner, project, kind, identifier, fingerprint):
        service = {"cad": self.app.cad, "image": self.app.images}[kind]
        recipe = service.require_revision(owner, project, identifier, fingerprint)
        # Verify the bounded saved JSON artifact; no PNG/GLB/media is read.
        artifact = service.artifact(
            owner, project, SimpleNamespace(request_id=identifier, format="json")
        )
        return recipe, artifact["sha256"]

    def validate(self, owner, project, reference):
        if reference is None:
            return
        reference = CreativeReference.model_validate(reference)
        _, digest = self.source(
            owner,
            project,
            reference.source_kind,
            reference.source_request_id,
            reference.source_fingerprint,
        )
        if digest != reference.source_sha256:
            raise ServiceError(
                "reference_stale", "The source recipe export changed. Review a new handoff."
            )

    def prepare(self, sid, args):
        owner = self.app.sessions.require_owner(sid, {"renderer"})
        context = self.app.studio_context(sid)
        recipe, digest = self.source(
            owner,
            context["project_path"],
            args.source_kind,
            args.source_request_id,
            args.source_fingerprint,
        )
        if args.source_kind == "cad":
            parts = recipe["objects"] if recipe["shape"] == "scene" else [recipe]
            summary = []
            for index, part in enumerate(parts, 1):
                dimensions = " × ".join(f"{part[key]:g}" for key in ("width", "depth", "height"))
                text = f"{index}. {part['name'][:24]} — {part['shape']}; {dimensions} mm; wall {part['thickness']:g} mm"
                if "material" in part:
                    text += f"; {part['material']}"
                    for key, unit in (("position", "mm"), ("rotation", "degrees"), ("scale", "")):
                        text += (
                            f"; {key} "
                            + ", ".join(f"{number:g}" for number in part[key])
                            + f" {unit}"
                        )
                summary.append(text.rstrip())
            description = "\n".join(summary)
            if len(description) > 1500:
                description = description[:1450] + " [recipe summary shortened]"
        else:
            description = (
                "Saved image prompt (recipe text, not pixel analysis): " + recipe["prompt"][:1400]
            )
        direction = (
            "Create a new editable scene using supported boxes, brackets or open enclosures. "
            "Choose dimensions explicitly; do not infer measurements from image pixels."
            if args.destination == "cad"
            else "Create a visual concept inspired by the saved recipe."
        )
        prompt = f"{direction}\nReference recipe: {description}\nSource: {args.source_kind}/{args.source_request_id}."
        return HandoffDraft(
            project=context["project_path"].name,
            destination=args.destination,
            reference=CreativeReference(
                source_kind=args.source_kind,
                source_request_id=args.source_request_id,
                source_fingerprint=args.source_fingerprint,
                source_sha256=digest,
            ),
            source_name=recipe["name"],
            name=("Study of " + recipe["name"])[:60],
            prompt=prompt,
        ).model_dump(mode="json")
