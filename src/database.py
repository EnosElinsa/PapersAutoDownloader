"""Database module for managing downloaded papers."""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_FILENAME = "papers.db"


class PapersDatabase:
    """SQLite database for tracking downloaded papers."""

    def __init__(self, download_dir: Path):
        self._db_path = download_dir / DB_FILENAME
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database and create tables if needed."""
        # check_same_thread=False allows connection to be used across threads (for GUI)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        
        cursor = self._conn.cursor()
        
        # Papers table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                arnumber TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT,
                publication TEXT,
                year INTEGER,
                doi TEXT,
                abstract TEXT,
                status TEXT DEFAULT 'pending',
                file_path TEXT,
                file_size INTEGER,
                error_message TEXT,
                task_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES download_tasks(id)
            )
        """)
        
        # Download tasks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS download_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT,
                search_url TEXT,
                max_results INTEGER,
                total_found INTEGER,
                downloaded_count INTEGER DEFAULT 0,
                skipped_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
        
        # Create indexes for faster queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_task_id ON papers(task_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON download_tasks(status)")
        
        self._conn.commit()
        logger.debug(f"Database initialized: {self._db_path}")

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ========== Task Management ==========

    def create_task(
        self,
        query: Optional[str] = None,
        search_url: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> int:
        """Create a new download task and return its ID."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO download_tasks (query, search_url, max_results)
            VALUES (?, ?, ?)
            """,
            (query, search_url, max_results),
        )
        self._conn.commit()
        task_id = cursor.lastrowid
        logger.debug(f"Created task {task_id}")
        return task_id

    def update_task_stats(
        self,
        task_id: int,
        total_found: Optional[int] = None,
        downloaded_count: Optional[int] = None,
        skipped_count: Optional[int] = None,
        failed_count: Optional[int] = None,
    ) -> None:
        """Update task statistics."""
        updates = []
        values = []
        
        if total_found is not None:
            updates.append("total_found = ?")
            values.append(total_found)
        if downloaded_count is not None:
            updates.append("downloaded_count = ?")
            values.append(downloaded_count)
        if skipped_count is not None:
            updates.append("skipped_count = ?")
            values.append(skipped_count)
        if failed_count is not None:
            updates.append("failed_count = ?")
            values.append(failed_count)
        
        if updates:
            values.append(task_id)
            self._conn.execute(
                f"UPDATE download_tasks SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            self._conn.commit()

    def complete_task(self, task_id: int, status: str = "completed") -> None:
        """Mark a task as completed."""
        self._conn.execute(
            """
            UPDATE download_tasks 
            SET status = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, task_id),
        )
        self._conn.commit()
        logger.debug(f"Task {task_id} marked as {status}")

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get task by ID."""
        cursor = self._conn.execute(
            "SELECT * FROM download_tasks WHERE id = ?", (task_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_recent_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent download tasks."""
        cursor = self._conn.execute(
            """
            SELECT * FROM download_tasks 
            ORDER BY created_at DESC 
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def delete_task(self, task_id: int) -> None:
        """Delete a task and its associated papers."""
        # Delete associated papers first
        self._conn.execute("DELETE FROM papers WHERE task_id = ?", (task_id,))
        # Delete the task
        self._conn.execute("DELETE FROM download_tasks WHERE id = ?", (task_id,))
        self._conn.commit()
        logger.debug(f"Task {task_id} and associated papers deleted")

    # ========== Paper Management ==========

    def paper_exists(self, arnumber: str) -> bool:
        """Check if a paper with this arnumber already exists."""
        cursor = self._conn.execute(
            "SELECT 1 FROM papers WHERE arnumber = ?", (arnumber,)
        )
        return cursor.fetchone() is not None

    def is_paper_downloaded(self, arnumber: str) -> bool:
        """Check if a paper has been successfully downloaded."""
        cursor = self._conn.execute(
            "SELECT status FROM papers WHERE arnumber = ?", (arnumber,)
        )
        row = cursor.fetchone()
        return row is not None and row["status"] == "downloaded"

    def get_paper(self, arnumber: str) -> Optional[Dict[str, Any]]:
        """Get paper by arnumber."""
        cursor = self._conn.execute(
            "SELECT * FROM papers WHERE arnumber = ?", (arnumber,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def add_paper(
        self,
        arnumber: str,
        title: str,
        task_id: Optional[int] = None,
        authors: Optional[List[str]] = None,
        publication: Optional[str] = None,
        year: Optional[int] = None,
        doi: Optional[str] = None,
        abstract: Optional[str] = None,
        status: str = "pending",
    ) -> None:
        """Add a new paper to the database."""
        authors_json = json.dumps(authors) if authors else None
        
        self._conn.execute(
            """
            INSERT OR IGNORE INTO papers 
            (arnumber, title, authors, publication, year, doi, abstract, status, task_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (arnumber, title, authors_json, publication, year, doi, abstract, status, task_id),
        )
        self._conn.commit()

    def update_paper_status(
        self,
        arnumber: str,
        status: str,
        file_path: Optional[str] = None,
        file_size: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update paper download status."""
        self._conn.execute(
            """
            UPDATE papers 
            SET status = ?, file_path = ?, file_size = ?, error_message = ?, 
                updated_at = CURRENT_TIMESTAMP
            WHERE arnumber = ?
            """,
            (status, file_path, file_size, error_message, arnumber),
        )
        self._conn.commit()
        logger.debug(f"Paper {arnumber} status updated to {status}")

    def mark_downloaded(
        self, arnumber: str, file_path: str, file_size: Optional[int] = None
    ) -> None:
        """Mark a paper as successfully downloaded."""
        self.update_paper_status(
            arnumber=arnumber,
            status="downloaded",
            file_path=file_path,
            file_size=file_size,
        )

    def mark_skipped(self, arnumber: str, reason: str) -> None:
        """Mark a paper as skipped."""
        self.update_paper_status(
            arnumber=arnumber,
            status="skipped",
            error_message=reason,
        )

    def mark_failed(self, arnumber: str, error: str) -> None:
        """Mark a paper as failed."""
        self.update_paper_status(
            arnumber=arnumber,
            status="failed",
            error_message=error,
        )

    # ========== Query Methods ==========

    def get_papers_by_status(
        self, status: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get papers filtered by status."""
        query = "SELECT * FROM papers WHERE status = ? ORDER BY updated_at DESC"
        if limit:
            query += f" LIMIT {limit}"
        cursor = self._conn.execute(query, (status,))
        return [dict(row) for row in cursor.fetchall()]

    def get_failed_papers(self) -> List[Dict[str, Any]]:
        """Get all failed papers for retry."""
        return self.get_papers_by_status("failed")

    def search_papers(self, keyword: str) -> List[Dict[str, Any]]:
        """Search papers by title or abstract."""
        cursor = self._conn.execute(
            """
            SELECT * FROM papers 
            WHERE title LIKE ? OR abstract LIKE ?
            ORDER BY updated_at DESC
            """,
            (f"%{keyword}%", f"%{keyword}%"),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, int]:
        """Get download statistics."""
        cursor = self._conn.execute(
            """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'downloaded' THEN 1 ELSE 0 END) as downloaded,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(COALESCE(file_size, 0)) as total_size
            FROM papers
            """
        )
        row = cursor.fetchone()
        return {
            "total": row["total"] or 0,
            "downloaded": row["downloaded"] or 0,
            "skipped": row["skipped"] or 0,
            "failed": row["failed"] or 0,
            "pending": row["pending"] or 0,
            "total_size_mb": round((row["total_size"] or 0) / (1024 * 1024), 2),
        }

    def export_to_json(self, output_path: Path) -> int:
        """Export all papers to JSON file. Returns count."""
        cursor = self._conn.execute("SELECT * FROM papers ORDER BY created_at")
        papers = [dict(row) for row in cursor.fetchall()]
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(papers, f, ensure_ascii=False, indent=2, default=str)
        
        return len(papers)

    def export_to_csv(self, output_path: Path) -> int:
        """Export all papers to CSV file. Returns count."""
        import csv
        
        cursor = self._conn.execute("SELECT * FROM papers ORDER BY created_at")
        rows = cursor.fetchall()
        
        if not rows:
            return 0
        
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(rows[0].keys())  # Header
            for row in rows:
                writer.writerow(row)
        
        return len(rows)

    # ========== Migration ==========

    def migrate_from_jsonl(self, jsonl_path: Path) -> int:
        """Migrate data from old JSONL state file. Returns count."""
        if not jsonl_path.exists():
            logger.warning(f"JSONL file not found: {jsonl_path}")
            return 0
        
        count = 0
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    arnumber = record.get("arnumber")
                    if not arnumber:
                        continue
                    
                    # Map old status to new
                    status = record.get("status", "pending")
                    
                    self._conn.execute(
                        """
                        INSERT OR IGNORE INTO papers 
                        (arnumber, title, status, file_path, error_message)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            arnumber,
                            record.get("title", "Unknown"),
                            status,
                            record.get("file"),
                            record.get("error"),
                        ),
                    )
                    count += 1
                except json.JSONDecodeError:
                    continue
        
        self._conn.commit()
        logger.info(f"Migrated {count} records from JSONL")
        return count
