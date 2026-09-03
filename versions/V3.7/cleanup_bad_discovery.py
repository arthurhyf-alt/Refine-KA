import pathlib
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parent
DB = ROOT / "data" / "pipeline.db"

if DB.exists():
    conn = sqlite3.connect(DB)
    document_ids = [row[0] for row in conn.execute(
        "SELECT id FROM documents WHERE source_id LIKE 'discovered-%'"
    )]
    if document_ids:
        marks = ",".join("?" for _ in document_ids)
        conn.execute(f"DELETE FROM observations WHERE document_id IN ({marks})", document_ids)
        conn.execute(f"DELETE FROM documents WHERE id IN ({marks})", document_ids)
    conn.commit()
    conn.close()
    print(f"removed_discovered_documents={len(document_ids)}")
else:
    print("removed_discovered_documents=0")
