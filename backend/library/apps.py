from django.apps import AppConfig


class LibraryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "library"

    def ready(self):
        from django.db.backends.signals import connection_created

        def _set_sqlite_pragmas(sender, connection, **kwargs):
            if connection.vendor != "sqlite":
                return
            with connection.cursor() as cursor:
                # WAL: readers and writers don't block each other.
                cursor.execute("PRAGMA journal_mode=WAL;")
                # NORMAL: safe but ~3× faster than default FULL sync.
                cursor.execute("PRAGMA synchronous=NORMAL;")
                # 10 MB page cache in memory.
                cursor.execute("PRAGMA cache_size=-10000;")
                # Store temp tables in memory instead of disk.
                cursor.execute("PRAGMA temp_store=MEMORY;")

        connection_created.connect(_set_sqlite_pragmas)
