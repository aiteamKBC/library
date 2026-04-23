from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_date

from library.models import Category, Resource
from library.seed_data import CATEGORIES, RESOURCES


class Command(BaseCommand):
    help = "Import the current library catalog into the database."

    def handle(self, *args, **options):
        category_lookup = {item["id"]: item for item in CATEGORIES}

        for item in RESOURCES:
            category_meta = category_lookup.get(item["categoryId"], {})
            category, _ = Category.objects.update_or_create(
                slug=item["categoryId"],
                defaults={
                    "name": item["category"],
                    "color": category_meta.get("color", "#442F73"),
                    "icon": category_meta.get("icon", "ri-book-open-line"),
                },
            )
            resource, _ = Resource.objects.update_or_create(
                id=item["id"],
                defaults={
                    "title": item["title"],
                    "description": item.get("description", ""),
                    "category": category,
                    "type": item.get("type", "Book"),
                    "level": item.get("level", ""),
                    "author": item["author"],
                    "publisher": item.get("publisher", ""),
                    "publication_year": item.get("publicationYear", ""),
                    "page_count": item.get("pageCount"),
                    "isbn13": item.get("isbn13", ""),
                    "isbn10": item.get("isbn10", ""),
                    "cover_image": item.get("coverImage", ""),
                    "info_link": item.get("infoLink", ""),
                    "date_added": parse_date(item.get("dateAdded", "")) or timezone.localdate(),
                    "featured": item.get("featured", False),
                    "popular": item.get("popular", False),
                    "cover_color": item.get("coverColor", "#442F73"),
                },
            )
            resource.ensure_copy_inventory()

        self.stdout.write(self.style.SUCCESS(f"Imported {len(RESOURCES)} books from the library seed catalog."))
