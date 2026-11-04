"""Knowledge map endpoints: the outline, its edits, imports, and topic linking."""

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import SEEDS_DIR
from app.db.knowledge_map import MapStore, parse_outline

router = APIRouter(prefix="/api/map", tags=["map"])


class NodeIn(BaseModel):
    text: str = ""
    parent_id: Optional[int] = None
    after_id: Optional[int] = None
    kind: str = "item"
    source: Optional[str] = None
    flag: bool = False


class NodePatch(BaseModel):
    text: Optional[str] = None
    flag: Optional[bool] = None
    source: Optional[str] = None


class MoveIn(BaseModel):
    parent_id: Optional[int] = None
    index: Optional[int] = None


class ShiftIn(BaseModel):
    op: str  # indent | outdent | up | down


class LinkIn(BaseModel):
    learning_id: int


class ImportIn(BaseModel):
    text: str
    parent_id: Optional[int] = None


class PlaceIn(BaseModel):
    links: list[dict]  # [{node_id, learning_id}]


def _missing():
    return JSONResponse({"error": "not found"}, status_code=404)


def _topic_ok(store: MapStore, learning_id: int) -> bool:
    row = store.db.fetch_one("SELECT is_active FROM learnings WHERE id = ?", (learning_id,))
    return bool(row and row["is_active"])


@router.get("")
def get_map():
    return MapStore().tree()


@router.post("/nodes")
def add_node(body: NodeIn):
    store = MapStore()
    if body.parent_id is not None and not store.get_node(body.parent_id):
        return _missing()
    nid = store.add_node(body.text, parent_id=body.parent_id, after_id=body.after_id,
                         kind=body.kind, source=body.source, flag=body.flag)
    return {"id": nid}


@router.put("/nodes/{node_id}")
def update_node(node_id: int, body: NodePatch):
    store = MapStore()
    if not store.get_node(node_id):
        return _missing()
    store.update_node(node_id, text=body.text, flag=body.flag, source=body.source)
    return {"ok": True}


@router.delete("/nodes/{node_id}")
def delete_node(node_id: int):
    store = MapStore()
    if not store.get_node(node_id):
        return _missing()
    return {"deleted": store.delete_node(node_id)}


@router.post("/nodes/{node_id}/move")
def move_node(node_id: int, body: MoveIn):
    ok = MapStore().move(node_id, body.parent_id, body.index)
    return {"ok": ok}


@router.post("/nodes/{node_id}/shift")
def shift_node(node_id: int, body: ShiftIn):
    return {"ok": MapStore().shift(node_id, body.op)}


@router.post("/nodes/{node_id}/link")
def link(node_id: int, body: LinkIn):
    store = MapStore()
    if not store.get_node(node_id) or not _topic_ok(store, body.learning_id):
        return _missing()
    store.link(node_id, body.learning_id)
    return {"ok": True}


@router.post("/nodes/{node_id}/unlink")
def unlink(node_id: int, body: LinkIn):
    MapStore().unlink(node_id, body.learning_id)
    return {"ok": True}


@router.get("/nodes/{node_id}/path")
def node_path(node_id: int):
    store = MapStore()
    if not store.get_node(node_id):
        return _missing()
    return {"path": store.path(node_id)}


@router.post("/import")
def import_outline(body: ImportIn):
    return {"added": MapStore().import_outline(body.text, body.parent_id)}


@router.get("/starters")
def starters():
    """Ready-made outlines in seeds/map/*.txt, offered when the map is empty."""
    out = []
    for path in sorted((SEEDS_DIR / "map").glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        name = path.stem.replace("_", " ").strip().capitalize()
        out.append({"name": name, "text": text, "items": len(parse_outline(text))})
    return {"starters": out}


@router.get("/learning/{learning_id}")
def learning_nodes(learning_id: int):
    return {"nodes": MapStore().nodes_for_learning(learning_id)}


@router.post("/suggest")
def suggest():
    """Pair unplaced topics with map nodes; embeddings sharpen it when running."""
    from app.services.embeddings import get_embeddings
    store = MapStore()
    vectors, embed = None, None
    emb = get_embeddings()
    if emb.model_available():
        vectors = dict(emb.all_vectors())

        def embed(texts: list[str]) -> list[list[float]]:
            out: list[list[float]] = []
            for i in range(0, len(texts), 64):
                chunk = emb.embed_texts(texts[i:i + 64])
                if not chunk:
                    return []
                out += chunk
            return out
    return {"suggestions": store.suggest(vectors=vectors, embed=embed),
            "unplaced": len(store.unplaced_learnings(limit=1000)),
            "embeddings": vectors is not None}


@router.post("/place")
def place(body: PlaceIn):
    store = MapStore()
    n = 0
    for item in body.links:
        try:
            nid, lid = int(item["node_id"]), int(item["learning_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if store.get_node(nid) and _topic_ok(store, lid):
            store.link(nid, lid)
            n += 1
    return {"linked": n}
