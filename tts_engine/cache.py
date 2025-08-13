import os
import hashlib
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
import sqlite3
from datetime import datetime, timedelta

class TTSCache:
    """
    File-based caching system for TTS audio generation.
    Uses SHA256 hash of (text + voice + model) as cache key.
    """
    
    def __init__(self, cache_dir: str = "cache", max_cache_size_gb: float = 5.0, max_age_days: int = 30):
        self.cache_dir = Path(cache_dir)
        self.audio_dir = self.cache_dir / "audio"
        self.db_path = self.cache_dir / "cache.db"
        self.max_cache_size_bytes = int(max_cache_size_gb * 1024 * 1024 * 1024)
        self.max_age_days = max_age_days
        
        # Create directories
        self.cache_dir.mkdir(exist_ok=True)
        self.audio_dir.mkdir(exist_ok=True)
        
        # Initialize database
        self._init_db()
        
        # Clean old entries on startup
        self._cleanup_old_entries()
        
    def _init_db(self):
        """Initialize SQLite database for cache metadata"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_key TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    voice TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    last_accessed TIMESTAMP NOT NULL,
                    access_count INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at ON cache_entries(created_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_last_accessed ON cache_entries(last_accessed)
            """)
            conn.commit()
    
    def _generate_cache_key(self, text: str, voice: str, model_name: str) -> str:
        """Generate cache key from text, voice, and model"""
        # Normalize text (remove extra whitespace, convert to lowercase for consistency)
        normalized_text = " ".join(text.strip().lower().split())
        
        # Create cache key from text + voice + model
        cache_data = f"{normalized_text}|{voice.lower()}|{model_name}"
        return hashlib.sha256(cache_data.encode('utf-8')).hexdigest()
    
    def get_cached_audio(self, text: str, voice: str, model_name: str) -> Optional[str]:
        """
        Get cached audio file path if it exists.
        Returns None if not cached or cache is invalid.
        """
        cache_key = self._generate_cache_key(text, voice, model_name)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            result = cursor.execute(
                "SELECT * FROM cache_entries WHERE cache_key = ?",
                (cache_key,)
            ).fetchone()
            
            if not result:
                return None
            
            file_path = Path(result['file_path'])
            
            # Check if file still exists
            if not file_path.exists():
                # Remove stale cache entry
                cursor.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
                conn.commit()
                return None
            
            # Update access information
            cursor.execute("""
                UPDATE cache_entries 
                SET last_accessed = ?, access_count = access_count + 1
                WHERE cache_key = ?
            """, (datetime.now(), cache_key))
            conn.commit()
            
            return str(file_path)
    
    def cache_audio(self, text: str, voice: str, model_name: str, audio_file_path: str) -> bool:
        """
        Cache an audio file.
        Returns True if successfully cached, False otherwise.
        """
        if not os.path.exists(audio_file_path):
            return False
        
        cache_key = self._generate_cache_key(text, voice, model_name)
        
        # Generate cached file path
        file_extension = Path(audio_file_path).suffix
        cached_file_path = self.audio_dir / f"{cache_key}{file_extension}"
        
        try:
            # Copy audio file to cache directory
            import shutil
            shutil.copy2(audio_file_path, cached_file_path)
            
            file_size = cached_file_path.stat().st_size
            now = datetime.now()
            
            # Store cache entry in database
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO cache_entries 
                    (cache_key, text, voice, model_name, file_path, file_size, created_at, last_accessed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (cache_key, text, voice, model_name, str(cached_file_path), 
                      file_size, now, now))
                conn.commit()
            
            # Check if we need to cleanup old entries
            self._enforce_cache_limits()
            
            return True
            
        except Exception as e:
            print(f"Failed to cache audio: {e}")
            return False
    
    def _cleanup_old_entries(self):
        """Remove cache entries older than max_age_days"""
        cutoff_date = datetime.now() - timedelta(days=self.max_age_days)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get old entries
            old_entries = cursor.execute(
                "SELECT file_path FROM cache_entries WHERE created_at < ?",
                (cutoff_date,)
            ).fetchall()
            
            # Delete files
            for entry in old_entries:
                file_path = Path(entry['file_path'])
                if file_path.exists():
                    file_path.unlink()
            
            # Remove from database
            cursor.execute("DELETE FROM cache_entries WHERE created_at < ?", (cutoff_date,))
            conn.commit()
            
            if old_entries:
                print(f"Cleaned up {len(old_entries)} old cache entries")
    
    def _enforce_cache_limits(self):
        """Enforce cache size limits by removing least recently used entries"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Calculate total cache size
            total_size = cursor.execute(
                "SELECT SUM(file_size) FROM cache_entries"
            ).fetchone()[0] or 0
            
            if total_size <= self.max_cache_size_bytes:
                return
            
            print(f"Cache size ({total_size / 1024 / 1024:.1f} MB) exceeds limit, cleaning up...")
            
            # Get entries sorted by last access time (oldest first)
            old_entries = cursor.execute("""
                SELECT cache_key, file_path, file_size 
                FROM cache_entries 
                ORDER BY last_accessed ASC
            """).fetchall()
            
            # Remove entries until we're under the limit
            bytes_to_remove = total_size - self.max_cache_size_bytes
            bytes_removed = 0
            
            for entry in old_entries:
                if bytes_removed >= bytes_to_remove:
                    break
                
                # Delete file
                file_path = Path(entry['file_path'])
                if file_path.exists():
                    file_path.unlink()
                
                # Remove from database
                cursor.execute("DELETE FROM cache_entries WHERE cache_key = ?", (entry['cache_key'],))
                bytes_removed += entry['file_size']
            
            conn.commit()
            print(f"Removed {bytes_removed / 1024 / 1024:.1f} MB from cache")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Get basic stats
            stats = cursor.execute("""
                SELECT 
                    COUNT(*) as entry_count,
                    SUM(file_size) as total_size,
                    SUM(access_count) as total_accesses,
                    AVG(access_count) as avg_accesses
                FROM cache_entries
            """).fetchone()
            
            # Get recent stats (last 24 hours)
            recent_cutoff = datetime.now() - timedelta(days=1)
            recent_stats = cursor.execute("""
                SELECT COUNT(*) as recent_entries
                FROM cache_entries 
                WHERE last_accessed > ?
            """, (recent_cutoff,)).fetchone()
            
            # Get top voices
            top_voices = cursor.execute("""
                SELECT voice, COUNT(*) as count
                FROM cache_entries
                GROUP BY voice
                ORDER BY count DESC
                LIMIT 5
            """).fetchall()
            
            return {
                "entry_count": stats[0] or 0,
                "total_size_mb": round((stats[1] or 0) / 1024 / 1024, 1),
                "total_accesses": stats[2] or 0,
                "avg_accesses": round(stats[3] or 0, 1),
                "recent_entries_24h": recent_stats[0] or 0,
                "max_size_gb": self.max_cache_size_bytes / 1024 / 1024 / 1024,
                "max_age_days": self.max_age_days,
                "top_voices": [{"voice": v[0], "count": v[1]} for v in top_voices]
            }
    
    def clear_cache(self) -> bool:
        """Clear all cache entries"""
        try:
            # Remove all audio files
            import shutil
            if self.audio_dir.exists():
                shutil.rmtree(self.audio_dir)
                self.audio_dir.mkdir()
            
            # Clear database
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM cache_entries")
                conn.commit()
            
            return True
        except Exception as e:
            print(f"Failed to clear cache: {e}")
            return False

# Global cache instance
_cache_instance = None

def get_cache(cache_dir: str = "cache", max_cache_size_gb: float = 5.0, max_age_days: int = 30) -> TTSCache:
    """Get global cache instance"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = TTSCache(cache_dir, max_cache_size_gb, max_age_days)
    return _cache_instance