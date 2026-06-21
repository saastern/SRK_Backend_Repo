from django.core.management.base import BaseCommand

from apps.students.views import apply_class_orders


class Command(BaseCommand):
    help = (
        "Set Class.order from canonical names (L.K.G, U.K.G, 1..10) using exact "
        "matching, and delete empty junk classes. Same logic as the "
        "'Fix Class Order' button / POST /api/students/classes/set-orders/."
    )

    def handle(self, *args, **options):
        result = apply_class_orders()
        self.stdout.write(self.style.SUCCESS(result['message']))
        for row in result['updated']:
            self.stdout.write(f"  {row['name']} -> order {row['order']}")
        if result['deleted']:
            self.stdout.write(self.style.WARNING(f"  Deleted junk: {', '.join(result['deleted'])}"))
        for u in result['unrecognized']:
            self.stdout.write(self.style.WARNING(
                f"  Needs manual order: {u['name']} ({u['students']} students)"
            ))
